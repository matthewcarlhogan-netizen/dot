#!/usr/bin/env python3
"""Standalone live face swap.

Input: source image/video + physical webcam id.
Output: OpenCV window by default, optional Python virtual camera.
"""

from __future__ import annotations

import argparse
import os
import platform
import sys
import time
import warnings
from pathlib import Path
from typing import Literal

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
WINDOW_NAME = "DOT - Live Deepfake"

sys.path.insert(0, str(ROOT / "src"))

from runtime_guard import warn_nested_checkout  # noqa: E402
from dot.commons.utils import get_device  # noqa: E402
from dot.simswap import SimswapOption  # noqa: E402
from dot.simswap.fs_model import legacy_simswap_import_path  # noqa: E402
from dot.simswap.mediapipe.face_mesh import FaceMesh  # noqa: E402

PresetName = Literal["fast", "balanced", "natural", "natural-max"]
BackendName = Literal["simswap", "onnx"]
OutputName = Literal["window", "virtualcam", "both"]
StyleName = Literal["swap", "avatar"]

PRESETS: dict[PresetName, Path] = {
    "fast": ROOT / "configs" / "simswap.yaml",
    "balanced": ROOT / "configs" / "m2_8gb_balanced.yaml",
    "natural": ROOT / "configs" / "m2_8gb_natural.yaml",
    "natural-max": ROOT / "configs" / "m2_8gb_natural_max.yaml",
}


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def ensure_supported_model_config(config: dict) -> dict:
    if config.get("swap_type", "simswap") != "simswap":
        return config
    if int(config.get("crop_size", 224)) != 512:
        return config

    checkpoints_dir = Path(config.get("checkpoints_dir", "saved_models/simswap/checkpoints"))
    checkpoint_512 = checkpoints_dir / "512" / "550000_net_G.pth"
    if checkpoint_512.exists():
        return config

    print("[dot] 512px SimSwap checkpoint missing; falling back to 224px.")
    print(f"[dot] Missing: {checkpoint_512}")
    config = dict(config)
    config["crop_size"] = 224
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


def draw_fps(frame, fps: float):
    frame = np.ascontiguousarray(frame)
    cv2.putText(frame, f"FPS: {fps:.1f}", (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 3)
    cv2.putText(frame, f"FPS: {fps:.1f}", (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 1)
    return frame


def read_source_frame(path: Path) -> np.ndarray:
    if path.suffix.lower() in {".mp4", ".mov", ".avi", ".mkv", ".webm"}:
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
    frame = read_source_frame(source)
    detector = FaceMesh(
        static_image_mode=True,
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5,
        mode="None",
    )
    result = detector.get(frame, size)
    if result is None:
        raise RuntimeError(f"No face detected in source: {source}")
    crop = prepare_source_crop(result[0][0])
    output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output), crop):
        raise RuntimeError(f"Could not write prepared source: {output}")
    return output


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

    def close(self):
        self._cam.close()


class SimSwapBackend:
    def __init__(self, config: dict):
        self.config = config
        self.option = SimswapOption(
            use_gpu=True,
            crop_size=config.get("crop_size", 224),
            use_mask=config.get("use_mask", False),
        )

    def load(self, source: Path):
        config = self.config
        crop_size = config.get("crop_size", 224)
        print("[dot] Loading SimSwap models ...")
        self.option.create_model(
            opt_crop_size=crop_size,
            opt_fp16=config.get("use_fp16", False),
            max_num_faces=config.get("max_num_faces", 1),
            detection_threshold=config.get("detection_threshold", 0.6),
            min_detection_confidence=config.get("detection_threshold", 0.6),
            parsing_model_path=config.get("parsing_model_path"),
            arcface_model_path=config.get("arcface_model_path"),
            checkpoints_dir=config.get("checkpoints_dir"),
        )
        print("[dot] Loading source identity ...")
        self.option.change_option(str(source))
        print("[dot] Ready.")

    def process(self, frame):
        config = self.config
        return self.option.process_image(
            frame,
            use_cam=True,
            natural_color_match=config.get("natural_color_match", False),
            natural_color_match_strength=config.get("natural_color_match_strength", 0.65),
            natural_detail_enhance=config.get("natural_detail_enhance", False),
            natural_detail_enhance_strength=config.get("natural_detail_enhance_strength", 0.12),
            natural_preserve_occluders=config.get("natural_preserve_occluders", False),
            natural_occluder_threshold=config.get("natural_occluder_threshold", 0.10),
            natural_occluder_strength=config.get("natural_occluder_strength", 0.90),
            natural_blend_mode=config.get("natural_blend_mode", "alpha"),
            natural_blend_strength=config.get("natural_blend_strength", 1.0),
            natural_mask_blur=config.get("natural_mask_blur", 0),
        )


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

        source_frame = read_source_frame(source)
        detector = FaceMesh(
            static_image_mode=True,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=float(self.config.get("detection_threshold", 0.55)),
            mode="None",
        )
        result = detector.get(source_frame, 128)
        if result is None:
            raise RuntimeError(f"No face detected in source for ONNX backend: {source}")

        print("[dot] Preparing source crop and extracting ONNX identity ...")
        source_crop = result[0][0]
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


class AvatarBackend:
    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.detector = FaceMesh(
            static_image_mode=False,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=float(self.config.get("detection_threshold", 0.55)),
            min_tracking_confidence=0.5,
            mode="None",
        )
        self.skin_tint = np.array([170, 190, 220], dtype=np.float32)

    def load(self, source: Path):
        frame = read_source_frame(source)
        detector = FaceMesh(static_image_mode=True, max_num_faces=1, refine_landmarks=True, mode="None")
        result = detector.get(frame, 256)
        if result is not None:
            crop = prepare_source_crop(result[0][0])
            self.skin_tint = crop.reshape(-1, 3).mean(axis=0).astype(np.float32)
        print("[dot] Avatar style ready.")

    def _enlarge_region(self, image: np.ndarray, center: tuple[int, int], radius: int, strength: float) -> np.ndarray:
        height, width = image.shape[:2]
        cx, cy = center
        x0, x1 = max(0, cx - radius), min(width, cx + radius)
        y0, y1 = max(0, cy - radius), min(height, cy + radius)
        if x1 <= x0 or y1 <= y0:
            return image
        roi = image[y0:y1, x0:x1].copy()
        yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
        dx = xx - cx
        dy = yy - cy
        dist = np.sqrt(dx * dx + dy * dy)
        mask = np.clip(1.0 - dist / max(radius, 1), 0.0, 1.0) ** 2
        scale = 1.0 - strength * mask
        map_x = (cx + dx * scale).astype(np.float32) - x0
        map_y = (cy + dy * scale).astype(np.float32) - y0
        image[y0:y1, x0:x1] = cv2.remap(roi, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        return image

    def _stylize_crop(self, crop: np.ndarray) -> np.ndarray:
        crop = cv2.resize(crop, (256, 256), interpolation=cv2.INTER_CUBIC)
        smooth = cv2.bilateralFilter(crop, 9, 80, 80)
        quantized = (smooth // 32) * 32 + 16
        tint = np.full_like(quantized, self.skin_tint)
        stylized = cv2.addWeighted(quantized.astype(np.float32), 0.72, tint.astype(np.float32), 0.28, 0)
        stylized = np.clip(stylized, 0, 255).astype(np.uint8)
        stylized = self._enlarge_region(stylized, (92, 105), 34, 0.32)
        stylized = self._enlarge_region(stylized, (164, 105), 34, 0.32)
        stylized = self._enlarge_region(stylized, (128, 160), 26, 0.16)
        gray = cv2.cvtColor(stylized, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 55, 120)
        edges = cv2.dilate(edges, np.ones((2, 2), np.uint8), iterations=1)
        stylized[edges > 0] = (24, 24, 24)
        cv2.ellipse(stylized, (128, 132), (102, 120), 0, 0, 360, (32, 32, 32), 3)
        return stylized

    def process(self, frame):
        result = self.detector.get(frame, 256)
        if result is None:
            return frame
        avatar = self._stylize_crop(result[0][0])
        return soft_paste(frame, avatar, result[1][0], blur=31)


def make_backend(name: str, style: str, config: dict):
    if style == "avatar":
        return AvatarBackend(config)
    if name == "onnx":
        return OnnxBackend(config)
    return SimSwapBackend(config)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Local live face swap: source image/video + webcam -> output."
    )
    parser.add_argument("--source", default="data/source_face.webm")
    parser.add_argument("--camera", type=int, default=1)
    parser.add_argument("--backend", choices=["simswap", "onnx"], default="simswap")
    parser.add_argument("--style", choices=["swap", "avatar"], default="swap")
    parser.add_argument("--preset", choices=sorted(PRESETS), default="natural")
    parser.add_argument("--output", choices=["window", "virtualcam", "both"], default="window")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--prepare-source", help="write an aligned, lighting-normalized source image and exit")
    parser.add_argument("--no-fps", action="store_true")
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    warn_nested_checkout(ROOT)
    source = Path(args.source)
    if not source.exists():
        print(f"Source not found: {source}", file=sys.stderr)
        return 1

    if args.prepare_source:
        output = prepare_source_file(source, Path(args.prepare_source))
        print(output)
        return 0

    config_path = PRESETS[args.preset]
    config = ensure_supported_model_config(load_config(config_path))

    print("DOT live")
    print(f"  Source : {source}")
    print(f"  Camera : {args.camera}")
    print(f"  Backend: {args.backend}")
    print(f"  Style  : {args.style}")
    print(f"  Preset : {args.preset}")
    print(f"  Output : {args.output}")
    print(f"  Device : {get_device()}")
    print(f"  Memory : {psutil.virtual_memory().available / (1024 ** 3):.1f}GB available")
    print()

    virtualcam = None
    cap = None
    show_window = args.output in {"window", "both"}
    try:
        if args.output in {"virtualcam", "both"}:
            virtualcam = VirtualCameraSink(args.width, args.height)

        backend = make_backend(args.backend, args.style, config)
        backend.load(source)
        cap = open_camera(args.camera, args.width, args.height)

        if show_window:
            cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_GUI_NORMAL)
            cv2.moveWindow(WINDOW_NAME, 500, 250)

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

            if not args.no_fps and show_window:
                swapped = draw_fps(swapped, fps)
            if show_window:
                cv2.imshow(WINDOW_NAME, swapped)
            if virtualcam:
                virtualcam.send_bgr(swapped)

            key = cv2.waitKey(1) if show_window else -1
            if key in {ord("q"), 27}:
                break
    finally:
        if cap:
            cap.release()
        if virtualcam:
            virtualcam.close()
        if show_window:
            cv2.destroyAllWindows()

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
