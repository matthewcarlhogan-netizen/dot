#!/usr/bin/env python3
"""Standalone highest-quality live face swap.

Input: source image/video + physical webcam id.
Output: virtual camera feed only.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import sys
import time
import warnings
from pathlib import Path

import cv2
import numpy as np
import psutil
import torch
import torch.nn.functional as F
import yaml

os.environ.setdefault("GLOG_minloglevel", "2")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
warnings.filterwarnings("ignore", message="SymbolDatabase.GetPrototype.*")

ROOT = Path(__file__).resolve().parent

sys.path.insert(0, str(ROOT / "src"))

from runtime_guard import warn_nested_checkout  # noqa: E402
from dot.commons.utils import get_device  # noqa: E402
from dot.simswap.fs_model import legacy_simswap_import_path  # noqa: E402
from dot.simswap.mediapipe.face_mesh import FaceMesh  # noqa: E402

HIGHEST_QUALITY_PRESET = ROOT / "configs" / "m2_8gb_natural_max.yaml"
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def ensure_highest_quality_model_config(config: dict) -> dict:
    if config.get("swap_type", "simswap") != "simswap":
        raise RuntimeError("Highest-quality mode requires swap_type: simswap in preset config.")

    checkpoints_dir = Path(config.get("checkpoints_dir", "saved_models/simswap/checkpoints"))
    checkpoint_512 = checkpoints_dir / "512" / "550000_net_G.pth"
    if not checkpoint_512.exists():
        raise RuntimeError(
            "Highest-quality mode requires the 512px SimSwap checkpoint at "
            f"{checkpoint_512}."
        )
    return config


def open_camera(camera_id: int, width: int, height: int) -> cv2.VideoCapture:
    backend = cv2.CAP_AVFOUNDATION if platform.system() == "Darwin" else cv2.CAP_ANY
    cap = cv2.VideoCapture(camera_id, backend)
    if not cap.isOpened():
        cap.release()
        cap = cv2.VideoCapture(camera_id)
    if not cap.isOpened():
        raise RuntimeError(
            f"Camera {camera_id} is not available. On macOS, grant Camera "
            "permission to the terminal app, then restart the terminal."
        )

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    ok, frame = cap.read()
    if not ok or frame is None or frame.size == 0:
        cap.release()
        raise RuntimeError(
            f"Camera {camera_id} opened but returned no frames. Close other apps "
            "using the camera and rerun."
        )
    return cap


def reopen_camera(camera_id: int, width: int, height: int) -> cv2.VideoCapture:
    print(f"[dot] Attempting to reopen camera {camera_id} ...")
    return open_camera(camera_id, width, height)


def read_source_frame(path: Path) -> np.ndarray:
    if path.suffix.lower() in VIDEO_EXTENSIONS:
        cap = cv2.VideoCapture(str(path))
        try:
            ok, frame = cap.read()
            if ok and frame is not None:
                return frame
        finally:
            cap.release()
        raise RuntimeError(f"Cannot read a frame from source video: {path}")

    frame = cv2.imread(str(path))
    if frame is None:
        raise RuntimeError(f"Cannot read source image: {path}")
    return frame


def pick_source_frame_with_face(source: Path, size: int = 256, max_frames: int = 120, stride: int = 3) -> np.ndarray:
    if source.suffix.lower() not in VIDEO_EXTENSIONS:
        return read_source_frame(source)

    detector = FaceMesh(
        static_image_mode=True,
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5,
        mode="None",
    )
    cap = cv2.VideoCapture(str(source))
    fallback = None
    try:
        idx = 0
        while idx < max_frames:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            if fallback is None:
                fallback = frame
            if idx % stride == 0 and detector.get(frame, size) is not None:
                return frame
            idx += 1
    finally:
        cap.release()
    if fallback is not None:
        return fallback
    raise RuntimeError(f"Cannot read a frame from source video: {source}")


def detect_source_face(
    frame: np.ndarray,
    size: int = 256,
    detection_threshold: float = 0.5,
) -> tuple[np.ndarray, np.ndarray]:
    detector = FaceMesh(
        static_image_mode=True,
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=detection_threshold,
        mode="None",
    )
    result = detector.get(frame, size)
    if result is None:
        raise RuntimeError("No face detected in selected source frame.")
    crops, matrices = result
    return crops[0], matrices[0]


def load_source_face_crop(
    source: Path,
    size: int = 256,
    detection_threshold: float = 0.5,
) -> np.ndarray:
    frame = pick_source_frame_with_face(source, size=size)
    crop, _ = detect_source_face(frame, size=size, detection_threshold=detection_threshold)
    return crop


def prepare_source_crop(crop: np.ndarray) -> np.ndarray:
    """Normalize source crop lighting before extracting identity."""
    lab = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB)
    light, a_chan, b_chan = cv2.split(lab)
    light = cv2.createCLAHE(clipLimit=1.6, tileGridSize=(8, 8)).apply(light)
    normalized = cv2.cvtColor(cv2.merge((light, a_chan, b_chan)), cv2.COLOR_LAB2BGR)
    return cv2.bilateralFilter(normalized, 5, 35, 35)


def arcface_embedding(net_arc, crop_bgr: np.ndarray, device: str) -> np.ndarray:
    crop_bgr = prepare_source_crop(crop_bgr)
    rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    tensor = torch.from_numpy(rgb.transpose(2, 0, 1)).unsqueeze(0)
    mean = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
    std = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)
    tensor = ((tensor - mean) / std).to(device)
    tensor = F.interpolate(tensor, size=(112, 112), mode="bilinear", align_corners=False)
    with torch.no_grad():
        embedding = net_arc(tensor).detach().cpu().numpy().astype(np.float32)
    norm = np.linalg.norm(embedding, axis=1, keepdims=True).clip(min=1e-6)
    return embedding / norm


def prepare_source_file(source: Path, output: Path, size: int = 256) -> Path:
    try:
        crop = load_source_face_crop(source, size=size, detection_threshold=0.5)
    except RuntimeError as exc:
        raise RuntimeError(f"No face detected in source: {source}") from exc
    crop = prepare_source_crop(crop)
    output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output), crop):
        raise RuntimeError(f"Could not write prepared source: {output}")
    return output


def prepared_source_cache_path(source: Path, cache_dir: Path) -> Path:
    stat = source.stat()
    key = f"{source.resolve()}::{stat.st_mtime_ns}::{stat.st_size}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return cache_dir / f"{source.stem}-{digest}.png"


def resolve_source_for_backend(source: Path, prepare_source: bool, cache_dir: Path) -> Path:
    if not prepare_source:
        return source
    out = prepared_source_cache_path(source, cache_dir)
    if out.exists():
        return out
    print(f"[dot] Preparing source identity: {source}")
    return prepare_source_file(source, out)


def soft_paste(frame: np.ndarray, patch: np.ndarray, matrix: np.ndarray, blur: int = 21) -> np.ndarray:
    height, width = frame.shape[:2]
    inverse = cv2.invertAffineTransform(matrix)
    warped = cv2.warpAffine(patch, inverse, (width, height), borderMode=cv2.BORDER_REFLECT)
    mask = np.zeros(patch.shape[:2], dtype=np.uint8)
    cv2.ellipse(
        mask,
        (patch.shape[1] // 2, patch.shape[0] // 2),
        (int(patch.shape[1] * 0.43), int(patch.shape[0] * 0.50)),
        0,
        0,
        360,
        255,
        -1,
    )
    mask = cv2.warpAffine(mask, inverse, (width, height), borderMode=cv2.BORDER_CONSTANT)
    if blur > 1:
        if blur % 2 == 0:
            blur += 1
        mask = cv2.GaussianBlur(mask, (blur, blur), 0)
    alpha = (mask.astype(np.float32) / 255.0)[:, :, None]
    blended = warped.astype(np.float32) * alpha + frame.astype(np.float32) * (1.0 - alpha)
    return np.clip(blended, 0, 255).astype(np.uint8)


class VirtualCameraSink:
    def __init__(self, width: int, height: int, fps: int = 20):
        try:
            import pyvirtualcam
        except ImportError as exc:
            raise RuntimeError(
                "Virtual camera output requires pyvirtualcam. Install it in the "
                "dot environment and initialize a supported virtual camera provider "
                "first, for example OBS 30+ on macOS 13+."
            ) from exc

        self._pyvirtualcam = pyvirtualcam
        self._cam = pyvirtualcam.Camera(width=width, height=height, fps=fps)
        print(f"[dot] Virtual camera: {self._cam.device}")

    def send_bgr(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        self._cam.send(rgb)
        self._cam.sleep_until_next_frame()

    def close(self):
        self._cam.close()


class OnnxBackend:
    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.model_path = ROOT / "saved_models" / "onnx" / "inswapper_128_fp16.onnx"
        self.arcface_path = ROOT / "saved_models" / "simswap" / "arcface_model" / "arcface_checkpoint.tar"
        if not self.model_path.exists():
            raise RuntimeError(
                "ONNX backend requires saved_models/onnx/inswapper_128_fp16.onnx. "
                "The SimSwap backend is the installed default: use --backend simswap."
            )
        if not self.arcface_path.exists():
            raise RuntimeError(
                "ONNX backend requires saved_models/simswap/arcface_model/arcface_checkpoint.tar "
                "for source identity extraction."
            )
        self.detector = FaceMesh(
            static_image_mode=False,
            max_num_faces=int(self.config.get("max_num_faces", 1)),
            refine_landmarks=True,
            min_detection_confidence=float(self.config.get("detection_threshold", 0.55)),
            min_tracking_confidence=0.5,
            mode="None",
        )
        self.session = None
        self.source_embedding: np.ndarray | None = None

    def _load_arcface(self):
        device = get_device()
        with legacy_simswap_import_path():
            net_arc = torch.load(self.arcface_path, weights_only=False, map_location=device)
        net_arc = net_arc.to(device)
        net_arc.eval()
        return net_arc

    def _load_embedding_map(self) -> np.ndarray:
        try:
            import onnx
            from onnx import numpy_helper
        except ImportError as exc:
            raise RuntimeError(
                "ONNX backend needs the onnx package to extract inswapper's buff2fs "
                "embedding map. Install it with: conda run -n dot python -m pip install onnx"
            ) from exc

        model = onnx.load(str(self.model_path))
        for initializer in model.graph.initializer:
            if initializer.name == "buff2fs":
                return numpy_helper.to_array(initializer).astype(np.float32)
        raise RuntimeError("ONNX model is missing the buff2fs source embedding map.")

    def load(self, source: Path):
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise RuntimeError("ONNX backend requires onnxruntime in the dot environment.") from exc

        available = ort.get_available_providers()
        providers = [provider for provider in ("CoreMLExecutionProvider", "CPUExecutionProvider") if provider in available]
        providers = providers or available
        print("[dot] Loading ONNX inswapper ...")
        self.session = ort.InferenceSession(str(self.model_path), providers=providers)
        print(f"[dot] ONNX providers: {', '.join(self.session.get_providers())}")

        print("[dot] Preparing source crop and extracting ONNX identity ...")
        detection_threshold = float(self.config.get("detection_threshold", 0.55))
        source_crop = load_source_face_crop(
            source=source,
            size=128,
            detection_threshold=detection_threshold,
        )
        net_arc = self._load_arcface()
        embedding = arcface_embedding(net_arc, source_crop, get_device())
        del net_arc
        if torch.backends.mps.is_available() and hasattr(torch, "mps"):
            torch.mps.empty_cache()

        embedding_map = self._load_embedding_map()
        embedding = np.dot(embedding, embedding_map)
        embedding = embedding / np.linalg.norm(embedding, axis=1, keepdims=True).clip(min=1e-6)
        self.source_embedding = embedding.astype(np.float32)
        print("[dot] Ready.")

    def process(self, frame):
        if self.session is None or self.source_embedding is None:
            raise RuntimeError("ONNX backend was not loaded.")

        result = self.detector.get(frame, 128)
        if result is None:
            return frame

        output = frame
        crops, matrices = result
        for crop, matrix in zip(crops, matrices):
            rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB).astype(np.float32)
            target = ((rgb - 127.5) / 127.5).transpose(2, 0, 1)[None, ...].astype(np.float32)
            prediction = self.session.run(None, {"target": target, "source": self.source_embedding})[0]
            fake_rgb = prediction[0].transpose(1, 2, 0)
            fake_rgb = np.clip(fake_rgb * 127.5 + 127.5, 0, 255).astype(np.uint8)
            fake_bgr = cv2.cvtColor(fake_rgb, cv2.COLOR_RGB2BGR)
            output = soft_paste(output, fake_bgr, matrix, blur=25)
        return output


def enforce_highest_quality_mode(args):
    args.preset = "natural-max"
    return args


def parse_args():
    parser = argparse.ArgumentParser(
        description="Local live face swap: source image/video + webcam -> highest-quality virtual camera feed."
    )
    parser.add_argument("--source", default="data/source_face.webm")
    parser.add_argument("--camera", type=int, default=1)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--prepare-source", help="write an aligned, lighting-normalized source image and exit")
    parser.add_argument("--source-cache-dir", default=str(ROOT / ".cache" / "prepared_sources"))
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = enforce_highest_quality_mode(parse_args())
    warn_nested_checkout(ROOT)
    source = Path(args.source)
    if not source.exists():
        print(f"Source not found: {source}", file=sys.stderr)
        return 1

    if args.prepare_source:
        output = prepare_source_file(source, Path(args.prepare_source))
        print(output)
        return 0

    config_path = HIGHEST_QUALITY_PRESET
    config = ensure_highest_quality_model_config(load_config(config_path))

    print("DOT live")
    print(f"  Source : {source}")
    print(f"  Camera : {args.camera}")
    print("  Backend: onnx")
    print("  Style  : swap")
    print(f"  Preset : {args.preset}")
    print("  Output : virtualcam")
    print(f"  Device : {get_device()}")
    print(f"  Memory : {psutil.virtual_memory().available / (1024 ** 3):.1f}GB available")
    print()

    virtualcam = None
    cap = None
    try:
        virtualcam = VirtualCameraSink(args.width, args.height)

        prepared_source = resolve_source_for_backend(
            source=source,
            prepare_source=True,
            cache_dir=Path(args.source_cache_dir),
        )
        print(f"  Engine : source={prepared_source}")

        backend = OnnxBackend(config)
        backend.load(prepared_source)
        cap = open_camera(args.camera, args.width, args.height)

        last = time.monotonic()
        fps = 0.0
        failed_reads = 0
        processing_failures = 0
        reopen_attempted = False
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                failed_reads += 1
                if failed_reads > 30:
                    if reopen_attempted:
                        raise RuntimeError("Camera stopped returning frames after recovery attempt.")
                    cap.release()
                    cap = reopen_camera(args.camera, args.width, args.height)
                    failed_reads = 0
                    reopen_attempted = True
                    continue
                time.sleep(0.03)
                continue
            failed_reads = 0
            reopen_attempted = False
            frame = cv2.flip(frame, 1)
            try:
                swapped = np.ascontiguousarray(backend.process(frame))
                processing_failures = 0
            except Exception as exc:
                processing_failures += 1
                if args.debug:
                    print(f"[dot] Frame processing error ({processing_failures}/5): {exc}", file=sys.stderr)
                if processing_failures >= 5:
                    raise RuntimeError(
                        f"Backend failed for {processing_failures} consecutive frames."
                    ) from exc
                swapped = frame

            now = time.monotonic()
            elapsed = max(now - last, 1e-6)
            last = now
            fps = 0.9 * fps + 0.1 * (1.0 / elapsed) if fps else 1.0 / elapsed

            virtualcam.send_bgr(swapped)
    finally:
        if cap:
            cap.release()
        if virtualcam:
            virtualcam.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nStopped.")
        raise SystemExit(0)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        if "--debug" in sys.argv:
            import traceback

            traceback.print_exc()
        raise SystemExit(1)
