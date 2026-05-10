"use client";

import {
  AlertTriangle,
  Camera,
  CheckCircle2,
  Download,
  FileUp,
  ImagePlus,
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

type ExportResponse = {
  ok: boolean;
  jobId?: string;
  status?: string;
  error?: string;
  billing?: {
    creditsConsumed: number;
    reason: string;
  };
};

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

  useEffect(() => {
    return () => {
      streamRef.current?.getTracks().forEach((track) => track.stop());
      if (sourcePreview) URL.revokeObjectURL(sourcePreview);
      if (resultUrl) URL.revokeObjectURL(resultUrl);
    };
  }, [sourcePreview, resultUrl]);

  function handleSourceChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    setSourceFile(file);
    setResultUrl(null);
    setJobId(null);
    setError(null);

    if (sourcePreview) URL.revokeObjectURL(sourcePreview);
    setSourcePreview(file ? URL.createObjectURL(file) : null);
  }

  async function startCamera() {
    setError(null);
    setCameraState("starting");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          width: { ideal: 1280 },
          height: { ideal: 720 },
          facingMode: "user",
        },
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
      setCameraState("ready");
    } catch (cameraError) {
      setCameraState("blocked");
      setError(cameraError instanceof Error ? cameraError.message : "Camera permission failed.");
    }
  }

  function stopCamera() {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    setCameraState("idle");
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
      setError("Upload a source image or short video first.");
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

      const response = await fetch("/api/export", {
        method: "POST",
        body: form,
      });
      const data = (await response.json()) as ExportResponse;
      if (!response.ok || !data.ok) {
        throw new Error(data.error ?? "Export failed.");
      }

      if (resultUrl) URL.revokeObjectURL(resultUrl);
      setResultUrl(URL.createObjectURL(frameBlob));
      setJobId(data.jobId ?? null);
      setExportState("complete");
      setProgress(100);
    } catch (exportError) {
      setExportState("failed");
      setProgress(0);
      setError(exportError instanceof Error ? exportError.message : "Export failed.");
    }
  }

  const canExport = sourceFile && consent && cameraState === "ready" && exportState !== "uploading";
  const cameraLabel =
    cameraState === "ready"
      ? "Camera ready"
      : cameraState === "starting"
        ? "Starting camera"
        : cameraState === "blocked"
          ? "Camera blocked"
          : "Camera idle";

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
            </div>
          </div>
          <div className="step">
            <Sparkles size={18} />
            <div>
              <strong>Export</strong>
              <span>{exportState === "complete" ? "Ready" : "Short clip path"}</span>
            </div>
          </div>
        </div>

        <section className="control-group">
          <h2>Source</h2>
          <label className="file-input">
            <ImagePlus size={26} />
            <span>{sourceFile ? sourceFile.name : "Upload image or short video"}</span>
            <input accept="image/*,video/*" type="file" onChange={handleSourceChange} />
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

        <div className="notice">
          Paid checkout is locked until rights clearance, hosted inference, metering, and retry-safe billing.
        </div>
      </aside>

      <section className="canvas-stage" aria-label="Preview workspace">
        <div className="topbar">
          <span className="status-pill">
            {cameraState === "ready" ? <CheckCircle2 size={15} /> : <Video size={15} />}
            {cameraLabel}
          </span>
          <span className="status-pill">
            <ShieldCheck size={15} />
            Credits consumed: 0
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
              {sourceFile?.type.startsWith("image/") ? <img alt="" src={sourcePreview} /> : <FileUp size={28} />}
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
            <button className="secondary" disabled={cameraState === "starting"} onClick={startCamera} type="button">
              {cameraState === "starting" ? <Loader2 size={17} /> : <Play size={17} />}
              Start camera
            </button>
          )}
          <button className="primary" disabled={!canExport} onClick={createExport} type="button">
            {exportState === "uploading" || exportState === "capturing" ? <Loader2 size={17} /> : <Sparkles size={17} />}
            Create export
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
            {exportState === "uploading" && "Creating hosted-inference job."}
            {exportState === "complete" && "Export ready."}
            {exportState === "failed" && "Export failed without consuming credits."}
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
          <strong>Backend contract</strong>
          <span className="status-copy">
            The UI posts source, frame, and consent to <code>/api/export</code>. Replace the stub with GPU
            inference without changing the browser flow.
          </span>
        </div>
      </aside>
    </main>
  );
}
