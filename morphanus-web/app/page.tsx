"use client";

import {
  AlertTriangle,
  Camera,
  CheckCircle2,
  Download,
  RefreshCw,
  ImagePlus,
  Key,
  Loader2,
  Play,
  ShieldCheck,
  Sparkles,
  Square,
  Upload,
  Video,
} from "lucide-react";
import { ChangeEvent, useEffect, useRef, useState } from "react";

type CameraState = "idle" | "starting" | "ready" | "blocked";
type ExportState = "idle" | "capturing" | "uploading" | "complete" | "failed";

function cameraPreferenceScore(label: string): number {
  const normalized = label.toLowerCase();
  let score = 0;
  if (normalized.includes("front")) score += 5;
  if (normalized.includes("user")) score += 4;
  if (normalized.includes("facetime")) score += 3;
  if (normalized.includes("selfie")) score += 3;
  if (normalized.includes("back")) score -= 2;
  if (normalized.includes("rear")) score -= 2;
  return score;
}

export default function Home() {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const [sourceFile, setSourceFile] = useState<File | null>(null);
  const [sourcePreview, setSourcePreview] = useState<string | null>(null);
  const [consent, setConsent] = useState(false);
  const [cameraState, setCameraState] = useState<CameraState>("idle");
  const [exportState, setExportState] = useState<ExportState>("idle");
  const [resultUrl, setResultUrl] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [videoDevices, setVideoDevices] = useState<MediaDeviceInfo[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState("");
  const [apiKey, setApiKey] = useState(() =>
    typeof window !== "undefined" ? localStorage.getItem("morphanus_api_key") ?? "" : "",
  );
  const [creditsRemaining, setCreditsRemaining] = useState<string | null>(null);

  async function refreshVideoDevices(preferredDeviceId?: string) {
    if (!navigator.mediaDevices?.enumerateDevices) {
      return;
    }
    const devices = (await navigator.mediaDevices.enumerateDevices()).filter(
      (device) => device.kind === "videoinput",
    );
    setVideoDevices(devices);
    setSelectedDeviceId((previous) => {
      if (preferredDeviceId && devices.some((device) => device.deviceId === preferredDeviceId)) {
        return preferredDeviceId;
      }
      if (previous && devices.some((device) => device.deviceId === previous)) {
        return previous;
      }
      if (!devices.length) {
        return "";
      }
      const ranked = [...devices].sort(
        (a, b) => cameraPreferenceScore(b.label) - cameraPreferenceScore(a.label),
      );
      return ranked[0].deviceId;
    });
  }

  useEffect(() => {
    return () => {
      streamRef.current?.getTracks().forEach((track) => track.stop());
      if (sourcePreview) URL.revokeObjectURL(sourcePreview);
      if (resultUrl) URL.revokeObjectURL(resultUrl);
    };
  }, [sourcePreview, resultUrl]);

  useEffect(() => {
    if (!navigator.mediaDevices?.enumerateDevices) {
      return;
    }
    const refresh = () => {
      void refreshVideoDevices();
    };
    refresh();
    navigator.mediaDevices.addEventListener?.("devicechange", refresh);
    return () => {
      navigator.mediaDevices.removeEventListener?.("devicechange", refresh);
    };
  }, []);

  function handleApiKeyChange(value: string) {
    setApiKey(value);
    if (typeof window !== "undefined") {
      localStorage.setItem("morphanus_api_key", value);
    }
  }

  function handleSourceChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    if (file && !file.type.startsWith("image/")) {
      setSourceFile(null);
      setResultUrl(null);
      setJobId(null);
      setError("Upload an image source for this export path.");
      if (sourcePreview) URL.revokeObjectURL(sourcePreview);
      setSourcePreview(null);
      event.target.value = "";
      return;
    }

    setSourceFile(file);
    setResultUrl(null);
    setJobId(null);
    setError(null);

    if (sourcePreview) URL.revokeObjectURL(sourcePreview);
    setSourcePreview(file ? URL.createObjectURL(file) : null);
  }

  async function startCamera(deviceIdOverride?: string) {
    setError(null);
    setCameraState("starting");
    const requestedDeviceId = deviceIdOverride ?? selectedDeviceId;
    const attempts: MediaStreamConstraints[] = [];
    if (requestedDeviceId) {
      attempts.push({
        audio: false,
        video: {
          deviceId: { exact: requestedDeviceId },
          width: { ideal: 1280 },
          height: { ideal: 720 },
        },
      });
    }
    attempts.push({
      audio: false,
      video: {
        width: { ideal: 1280 },
        height: { ideal: 720 },
        facingMode: { ideal: "user" },
      },
    });
    attempts.push({ audio: false, video: { facingMode: "user" } });
    attempts.push({ audio: false, video: true });

    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;

    let stream: MediaStream | null = null;
    let cameraError: unknown = null;
    try {
      for (const constraints of attempts) {
        try {
          stream = await navigator.mediaDevices.getUserMedia(constraints);
          break;
        } catch (error) {
          cameraError = error;
        }
      }
      if (!stream) {
        throw cameraError ?? new Error("Camera permission failed.");
      }
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
      const activeDeviceId = stream.getVideoTracks()[0]?.getSettings().deviceId;
      await refreshVideoDevices(activeDeviceId);
      setCameraState("ready");
    } catch (error) {
      setCameraState("blocked");
      setError(error instanceof Error ? error.message : "Camera permission failed.");
    }
  }

  function stopCamera() {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    setCameraState("idle");
  }

  async function switchCamera() {
    if (videoDevices.length < 2) {
      setError("No alternate front camera was detected on this device.");
      return;
    }
    const currentIndex = videoDevices.findIndex((device) => device.deviceId === selectedDeviceId);
    const nextIndex = currentIndex >= 0 ? (currentIndex + 1) % videoDevices.length : 0;
    const next = videoDevices[nextIndex];
    setSelectedDeviceId(next.deviceId);
    await startCamera(next.deviceId);
  }

  function drawProcessedFrame(): Promise<Blob> {
    return new Promise((resolve, reject) => {
      const video = videoRef.current;
      const canvas = canvasRef.current;
      const context = canvas?.getContext("2d");

      if (!video || !canvas || !context || video.videoWidth === 0 || video.videoHeight === 0) {
        reject(new Error("Camera preview is not ready."));
        return;
      }

      canvas.width = Math.min(video.videoWidth, 1280);
      canvas.height = Math.round((canvas.width / video.videoWidth) * video.videoHeight);
      context.drawImage(video, 0, 0, canvas.width, canvas.height);

      const overlay = context.createLinearGradient(0, 0, canvas.width, canvas.height);
      overlay.addColorStop(0, "rgba(112, 195, 173, 0.22)");
      overlay.addColorStop(1, "rgba(241, 195, 91, 0.12)");
      context.fillStyle = overlay;
      context.fillRect(0, 0, canvas.width, canvas.height);

      context.fillStyle = "rgba(12, 15, 18, 0.78)";
      context.fillRect(18, canvas.height - 54, 212, 36);
      context.fillStyle = "#f5f7f1";
      context.font = "700 16px system-ui";
      context.fillText("Morphanus Web MVP", 32, canvas.height - 31);

      canvas.toBlob(
        (blob) => {
          if (!blob) {
            reject(new Error("Could not capture a preview frame."));
            return;
          }
          resolve(blob);
        },
        "image/png",
        0.92,
      );
    });
  }

  async function createExport() {
    if (!sourceFile) {
      setError("Upload a source image first.");
      return;
    }
    if (!consent) {
      setError("Confirm consent before creating an export.");
      return;
    }
    if (cameraState !== "ready") {
      setError("Start the camera before creating an export.");
      return;
    }
    if (!apiKey) {
      setError("Enter your API key in the sidebar to continue.");
      return;
    }

    setError(null);
    setResultUrl(null);
    setJobId(null);
    setExportState("capturing");
    setProgress(25);

    try {
      const frameBlob = await drawProcessedFrame();
      setExportState("uploading");
      setProgress(65);

      const form = new FormData();
      form.append("source", sourceFile);
      form.append("frame", frameBlob, "camera-frame.png");
      form.append("consent", "true");
      form.append("api_key", apiKey);

      const response = await fetch("/api/export", {
        method: "POST",
        body: form,
      });

      if (!response.ok) {
        const text = await response.text();
        let message = text || `Export failed (${response.status}).`;
        try {
          const data = JSON.parse(text) as { error?: string; detail?: string };
          message = data.error ?? data.detail ?? message;
        } catch {
          // Keep the plain response text when the API does not return JSON.
        }
        throw new Error(message);
      }

      const imageBlob = await response.blob();
      const jobIdHeader = response.headers.get("x-job-id") ?? "";
      const creditsRemainingHeader = response.headers.get("x-credits-remaining") ?? "";

      if (creditsRemainingHeader) {
        setCreditsRemaining(creditsRemainingHeader);
      }

      if (resultUrl) URL.revokeObjectURL(resultUrl);
      setResultUrl(URL.createObjectURL(imageBlob));
      setJobId(jobIdHeader || null);
      setExportState("complete");
      setProgress(100);
    } catch (exportError) {
      setExportState("failed");
      setProgress(0);
      setError(exportError instanceof Error ? exportError.message : "Export failed.");
    }
  }

  const canExport = sourceFile && consent && cameraState === "ready" && exportState !== "uploading" && apiKey.length > 0;
  const cameraLabel =
    cameraState === "ready"
      ? "Camera ready"
      : cameraState === "starting"
        ? "Starting camera"
        : cameraState === "blocked"
          ? "Camera blocked"
          : "Camera idle";
  const selectedCameraLabel =
    videoDevices.find((device) => device.deviceId === selectedDeviceId)?.label ||
    (videoDevices.length ? "Front camera selected" : "Camera auto-select");

  return (
    <main className="app-shell">
      <aside className="rail">
        <div className="brand">
          <span className="mark">M</span>
          <div>
            <div className="brand-title">Morphanus Web</div>
            <div className="brand-subtitle">Universal browser MVP</div>
          </div>
        </div>

        <div className="step-list" aria-label="Workflow">
          <div className="step">
            <Upload size={18} />
            <div>
              <strong>Source</strong>
              <span>{sourceFile ? sourceFile.name : "Not selected"}</span>
            </div>
          </div>
          <div className="step">
            <Camera size={18} />
            <div>
              <strong>Camera</strong>
              <span>{cameraLabel}</span>
              <span>{selectedCameraLabel}</span>
            </div>
          </div>
          <div className="step">
            <Sparkles size={18} />
            <div>
              <strong>Export</strong>
              <span>{exportState === "complete" ? "Ready" : "Image export"}</span>
            </div>
          </div>
        </div>

        <section className="control-group">
          <h2>Source</h2>
          <label className="file-input">
            <ImagePlus size={26} />
            <span>{sourceFile ? sourceFile.name : "Upload source image"}</span>
            <input accept="image/*" type="file" onChange={handleSourceChange} />
          </label>
        </section>

        <section className="control-group">
          <h2>API Key</h2>
          <label className="file-input" style={{ padding: "6px 10px", gridTemplateColumns: "1fr" }}>
            <Key size={16} style={{ position: "absolute", margin: "6px 0 0 4px", opacity: 0.5 }} />
            <input
              value={apiKey}
              onChange={(e) => handleApiKeyChange(e.target.value)}
              placeholder="DOT-XXXXX-XXXXX-XXXXX"
              style={{
                width: "100%", background: "transparent", border: "none",
                color: "inherit", font: "inherit", paddingLeft: 22,
              }}
            />
          </label>
          {creditsRemaining && (
            <span className="small-copy" style={{ marginTop: 4, display: "block" }}>
              Credits remaining: {creditsRemaining}
            </span>
          )}
        </section>

        <section className="control-group">
          <h2>Camera</h2>
          <label className="small-copy" style={{ display: "grid", gap: 8 }}>
            <span>Preferred front camera</span>
            <select
              value={selectedDeviceId}
              onChange={(event) => setSelectedDeviceId(event.target.value)}
              style={{
                width: "100%",
                minHeight: 40,
                borderRadius: 7,
                border: "1px solid var(--line)",
                background: "var(--panel-strong)",
                color: "var(--text)",
                padding: "0 10px",
              }}
            >
              {!videoDevices.length && <option value="">Auto-select camera</option>}
              {videoDevices.map((device, index) => (
                <option key={device.deviceId || `video-${index}`} value={device.deviceId}>
                  {device.label || `Camera ${index + 1}`}
                </option>
              ))}
            </select>
          </label>
        </section>

        <section className="control-group">
          <h2>Consent</h2>
          <label className="toggle-row">
            <input checked={consent} onChange={(event) => setConsent(event.target.checked)} type="checkbox" />
            <span className="small-copy">
              I have permission to use the uploaded source and the camera subject for this export.
            </span>
          </label>
        </section>
      </aside>

      <section className="canvas-stage" aria-label="Preview workspace">
        <div className="topbar">
          <span className="status-pill">
            {cameraState === "ready" ? <CheckCircle2 size={15} /> : <Video size={15} />}
            {cameraLabel}
          </span>
          <span className="status-pill">
            <ShieldCheck size={15} />
            {creditsRemaining !== null ? `Credits: ${creditsRemaining}` : "Commerce enabled"}
          </span>
        </div>

        <div className="stage-frame">
          <video aria-label="Camera preview" muted playsInline ref={videoRef} />
          <canvas aria-hidden="true" ref={canvasRef} />
          {cameraState !== "ready" && (
            <div className="empty-state">
              <Camera size={42} />
              <strong>Camera preview</strong>
              <span className="status-copy">Open from localhost or HTTPS and allow camera access.</span>
            </div>
          )}
          {sourcePreview && (
            <div className="source-chip">
              <img alt="" src={sourcePreview} />
              <span>{sourceFile?.name}</span>
            </div>
          )}
        </div>

        <div className="actionbar">
          {cameraState === "ready" ? (
            <button className="danger" onClick={stopCamera} type="button">
              <Square size={17} />
              Stop
            </button>
          ) : (
            <button
              className="secondary"
              disabled={cameraState === "starting"}
              onClick={() => {
                void startCamera();
              }}
              type="button"
            >
              {cameraState === "starting" ? <Loader2 size={17} /> : <Play size={17} />}
              Start camera
            </button>
          )}
          <button className="primary" disabled={!canExport} onClick={createExport} type="button">
            {exportState === "uploading" || exportState === "capturing" ? <Loader2 size={17} /> : <Sparkles size={17} />}
            Create export
          </button>
          <button
            className="secondary"
            onClick={() => {
              void switchCamera();
            }}
            type="button"
          >
            <RefreshCw size={17} />
            Switch camera
          </button>
        </div>
      </section>

      <aside className="side-panel">
        <h2>Export</h2>
        <div className="panel-card">
          <strong>Status</strong>
          <span className="status-copy">
            {exportState === "idle" && "Waiting for source, consent, and camera."}
            {exportState === "capturing" && "Capturing browser preview."}
            {exportState === "uploading" && "Swapping face via ONNX inference."}
            {exportState === "complete" && "Export ready."}
            {exportState === "failed" && "Export failed."}
          </span>
          <div className="meter" aria-hidden="true">
            <span style={{ width: `${progress}%` }} />
          </div>
          {jobId && <span className="small-copy">Job {jobId}</span>}
          {error && (
            <span className="small-copy error">
              <AlertTriangle size={14} /> {error}
            </span>
          )}
        </div>

        {resultUrl && (
          <div className="panel-card">
            <strong>Result</strong>
            <img alt="Generated export preview" className="result-preview" src={resultUrl} />
            <a download="morphanus-web-export.png" href={resultUrl}>
              <button className="secondary" type="button">
                <Download size={17} />
                Download
              </button>
            </a>
          </div>
        )}

        <div className="panel-card">
          <strong>Backend</strong>
          <span className="status-copy">
            Live ONNX inswapper inference with API key billing. Credits deducted per export.
          </span>
        </div>
      </aside>
    </main>
  );
}
