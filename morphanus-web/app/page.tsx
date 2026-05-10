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

const MAX_SOURCE_BYTES = 25 * 1024 * 1024;
const ACCEPTED_SOURCE_PREFIXES = ["image/", "video/"];
const SOURCE_FRAME_TIMEOUT_MS = 4000;

type SourceFrame = {
  element: CanvasImageSource;
  width: number;
  height: number;
  cleanup: () => void;
};

function drawImageCover(
  context: CanvasRenderingContext2D,
  image: CanvasImageSource,
  sourceWidth: number,
  sourceHeight: number,
  x: number,
  y: number,
  width: number,
  height: number,
) {
  const sourceRatio = sourceWidth / sourceHeight;
  const targetRatio = width / height;
  let cropWidth = sourceWidth;
  let cropHeight = sourceHeight;
  let cropX = 0;
  let cropY = 0;

  if (sourceRatio > targetRatio) {
    cropWidth = sourceHeight * targetRatio;
    cropX = (sourceWidth - cropWidth) / 2;
  } else {
    cropHeight = sourceWidth / targetRatio;
    cropY = (sourceHeight - cropHeight) / 2;
  }

  context.drawImage(image, cropX, cropY, cropWidth, cropHeight, x, y, width, height);
}

function loadImageFrame(file: File): Promise<SourceFrame> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const image = new Image();

    image.onload = () => {
      resolve({
        element: image,
        width: image.naturalWidth,
        height: image.naturalHeight,
        cleanup: () => URL.revokeObjectURL(url),
      });
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Could not read the uploaded image source."));
    };
    image.src = url;
  });
}

function loadVideoFrame(file: File): Promise<SourceFrame> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const video = document.createElement("video");
    let settled = false;
    let timer: number | null = null;

    function cleanupUrl() {
      if (timer) window.clearTimeout(timer);
      URL.revokeObjectURL(url);
    }

    function resolveFrame() {
      if (settled || video.videoWidth === 0 || video.videoHeight === 0) return;
      settled = true;
      resolve({
        element: video,
        width: video.videoWidth,
        height: video.videoHeight,
        cleanup: cleanupUrl,
      });
    }

    function rejectFrame(message: string) {
      if (settled) return;
      settled = true;
      cleanupUrl();
      reject(new Error(message));
    }

    timer = window.setTimeout(() => {
      rejectFrame("Could not read a frame from the uploaded video source.");
    }, SOURCE_FRAME_TIMEOUT_MS);

    video.muted = true;
    video.playsInline = true;
    video.preload = "metadata";
    video.onloadeddata = resolveFrame;
    video.onseeked = resolveFrame;
    video.onerror = () => rejectFrame("Could not read the uploaded video source.");
    video.onloadedmetadata = () => {
      const seekTarget = Number.isFinite(video.duration) && video.duration > 0 ? Math.min(0.1, video.duration / 2) : 0;
      try {
        video.currentTime = seekTarget;
      } catch {
        resolveFrame();
      }
    };
    video.src = url;
    video.load();
  });
}

async function loadSourceFrame(file: File): Promise<SourceFrame> {
  if (file.type.startsWith("image/")) return loadImageFrame(file);
  if (file.type.startsWith("video/")) return loadVideoFrame(file);
  throw new Error("Choose an image or short video source.");
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

  useEffect(() => {
    return () => {
      streamRef.current?.getTracks().forEach((track) => track.stop());
      if (sourcePreview) URL.revokeObjectURL(sourcePreview);
      if (resultUrl) URL.revokeObjectURL(resultUrl);
    };
  }, [sourcePreview, resultUrl]);

  function handleSourceChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    setResultUrl(null);
    setJobId(null);
    setError(null);

    if (sourcePreview) URL.revokeObjectURL(sourcePreview);
    setSourcePreview(null);

    if (!file) {
      setSourceFile(null);
      return;
    }

    if (!ACCEPTED_SOURCE_PREFIXES.some((prefix) => file.type.startsWith(prefix))) {
      setSourceFile(null);
      setError("Choose an image or short video source.");
      return;
    }

    if (file.size > MAX_SOURCE_BYTES) {
      setSourceFile(null);
      setError("Source is over the 25MB web MVP limit.");
      return;
    }

    setSourceFile(file);
    setSourcePreview(URL.createObjectURL(file));
  }

  async function startCamera() {
    setError(null);
    setCameraState("starting");
    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error("This browser does not expose camera capture. Use a current Chrome, Edge, Safari, or Firefox build.");
      }
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
      setError(
        cameraError instanceof Error
          ? cameraError.message
          : "Camera permission failed. Use HTTPS or localhost and allow camera access.",
      );
    }
  }

  function stopCamera() {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    setCameraState("idle");
  }

  async function drawProcessedFrame(source: File): Promise<Blob> {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");

    if (!video || !canvas || !context || video.videoWidth === 0 || video.videoHeight === 0) {
      throw new Error("Camera preview is not ready.");
    }

    const sourceFrame = await loadSourceFrame(source);

    try {
      canvas.width = Math.min(video.videoWidth, 1280);
      canvas.height = Math.round((canvas.width / video.videoWidth) * video.videoHeight);
      context.drawImage(video, 0, 0, canvas.width, canvas.height);

      const overlay = context.createLinearGradient(0, 0, canvas.width, canvas.height);
      overlay.addColorStop(0, "rgba(112, 195, 173, 0.12)");
      overlay.addColorStop(1, "rgba(241, 195, 91, 0.08)");
      context.fillStyle = overlay;
      context.fillRect(0, 0, canvas.width, canvas.height);

      const injectionSize = Math.min(canvas.width * 0.36, canvas.height * 0.55);
      const injectionWidth = injectionSize * 0.78;
      const injectionHeight = injectionSize;
      const injectionX = (canvas.width - injectionWidth) / 2;
      const injectionY = canvas.height * 0.16;
      const radiusX = injectionWidth / 2;
      const radiusY = injectionHeight / 2;
      const centerX = injectionX + radiusX;
      const centerY = injectionY + radiusY;

      context.save();
      context.beginPath();
      context.ellipse(centerX, centerY, radiusX, radiusY, 0, 0, Math.PI * 2);
      context.clip();
      drawImageCover(
        context,
        sourceFrame.element,
        sourceFrame.width,
        sourceFrame.height,
        injectionX,
        injectionY,
        injectionWidth,
        injectionHeight,
      );
      context.globalCompositeOperation = "multiply";
      context.fillStyle = "rgba(255, 220, 170, 0.12)";
      context.fillRect(injectionX, injectionY, injectionWidth, injectionHeight);
      context.restore();
      context.globalCompositeOperation = "source-over";

      const feather = context.createRadialGradient(centerX, centerY, radiusX * 0.72, centerX, centerY, radiusX * 1.04);
      feather.addColorStop(0, "rgba(112, 195, 173, 0)");
      feather.addColorStop(1, "rgba(112, 195, 173, 0.58)");
      context.fillStyle = feather;
      context.beginPath();
      context.ellipse(centerX, centerY, radiusX * 1.04, radiusY * 1.04, 0, 0, Math.PI * 2);
      context.fill();

      context.strokeStyle = "rgba(245, 247, 241, 0.8)";
      context.lineWidth = Math.max(2, canvas.width * 0.003);
      context.beginPath();
      context.ellipse(centerX, centerY, radiusX, radiusY, 0, 0, Math.PI * 2);
      context.stroke();

      context.fillStyle = "rgba(12, 15, 18, 0.78)";
      context.fillRect(18, canvas.height - 54, 242, 36);
      context.fillStyle = "#f5f7f1";
      context.font = "700 16px system-ui";
      context.fillText("Source injected preview", 32, canvas.height - 31);

      return await new Promise<Blob>((resolve, reject) => {
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
    } finally {
      sourceFrame.cleanup();
    }
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
      const frameBlob = await drawProcessedFrame(sourceFile);
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

  const canExport = Boolean(
    sourceFile && consent && cameraState === "ready" && exportState !== "uploading" && exportState !== "capturing",
  );
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
