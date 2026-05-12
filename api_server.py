#!/usr/bin/env python3
"""Morphanus API server — hosted face-swap inference with key billing."""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Optional, Protocol

import cv2
import numpy as np
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

warnings = __import__("warnings")
warnings.filterwarnings("ignore", message="SymbolDatabase.GetPrototype.*")
os.environ.setdefault("GLOG_minloglevel", "2")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from runtime_guard import warn_nested_checkout  # noqa: E402
from dot.commons.utils import get_device  # noqa: E402

app = FastAPI(title="Morphanus API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

VPS_DIR = ROOT / "vps_portal"

class BackendProtocol(Protocol):
    _loaded: bool

    def load(self) -> None: ...

    def _prepare_source(self, image_bytes: bytes) -> np.ndarray: ...

    def _swap_target(self, image_bytes: bytes, source_embedding: np.ndarray) -> bytes: ...


_backend: Optional[BackendProtocol] = None


def _truthy_env(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _inference_mode() -> str:
    # research_nc: existing local research backend (may include non-commercial components)
    # commercial_external: paid-safe placeholder; wire to commercially cleared provider
    return os.getenv("MORPHANUS_INFERENCE_MODE", "research_nc").strip().lower()


def _paid_mode() -> bool:
    return _truthy_env("MORPHANUS_PAID_MODE", "0")


def _enforce_paid_inference_mode() -> None:
    if _paid_mode() and _inference_mode() != "commercial_external":
        raise HTTPException(
            status_code=503,
            detail=(
                "Paid mode requires MORPHANUS_INFERENCE_MODE=commercial_external. "
                "Current mode is non-commercial research backend."
            ),
        )


@contextmanager
def _billing_lock():
    VPS_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = VPS_DIR / ".billing.lock"
    with lock_path.open("a+") as handle:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            try:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, default: dict) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return default


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", dir=path.parent, delete=False) as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
        tmp_name = handle.name
    os.replace(tmp_name, path)


def _load_keys_unlocked() -> dict:
    return _read_json(VPS_DIR / "keys.json", {})


def _load_subs_unlocked() -> dict:
    return _read_json(VPS_DIR / "subscriptions.json", {"customers": {}, "invoices": {}})


def _load_keys() -> dict:
    with _billing_lock():
        return _load_keys_unlocked()


def _save_keys(keys: dict) -> None:
    _atomic_write_json(VPS_DIR / "keys.json", keys)


def _load_subs() -> dict:
    with _billing_lock():
        return _load_subs_unlocked()


def _save_subs(subs: dict) -> None:
    _atomic_write_json(VPS_DIR / "subscriptions.json", subs)


def _log_audit(entry: dict) -> None:
    p = VPS_DIR / "audit_log.jsonl"
    entry["at"] = _now()
    with _billing_lock():
        with p.open("a") as f:
            f.write(json.dumps(entry) + "\n")


def _validate_key_entry(api_key: str, keys: dict) -> dict:
    if api_key not in keys:
        raise HTTPException(status_code=401, detail="Invalid API key.")
    entry = keys[api_key]
    if not entry.get("active", False):
        raise HTTPException(status_code=403, detail="API key is deactivated.")
    expires = entry.get("expires_at")
    if expires and datetime.fromisoformat(expires) < datetime.now(timezone.utc):
        raise HTTPException(status_code=403, detail="API key has expired.")
    if entry.get("plan", "").startswith("uses_") and entry.get("uses_remaining", 0) <= 0:
        raise HTTPException(status_code=402, detail="No credits remaining.")
    return entry


def _validate_key(api_key: str) -> dict:
    with _billing_lock():
        return dict(_validate_key_entry(api_key, _load_keys_unlocked()))


def _deduct_credit(api_key: str) -> dict:
    with _billing_lock():
        keys = _load_keys_unlocked()
        entry = _validate_key_entry(api_key, keys)
        entry = dict(entry)
        plan = entry.get("plan", "")
        if plan.startswith("uses_"):
            remaining = entry.get("uses_remaining", 0)
            if remaining <= 0:
                raise HTTPException(status_code=402, detail="No credits remaining.")
            entry["uses_remaining"] = remaining - 1
            keys[api_key] = entry
            _save_keys(keys)

            subs = _load_subs_unlocked()
            email = entry.get("email", "")
            if email in subs.get("customers", {}):
                subs["customers"][email]["uses_remaining"] = entry["uses_remaining"]
                _save_subs(subs)
        return entry


def _credits_remaining(entry: dict) -> str:
    plan = entry.get("plan", "")
    if plan.startswith("uses_"):
        return str(entry.get("uses_remaining", 0))
    return "unlimited"


class InferenceBackend:
    """ONNX inswapper backend with lazy-loading for server use."""

    def __init__(self):
        self._loaded = False
        self.model_path = ROOT / "saved_models" / "onnx" / "inswapper_128_fp16.onnx"
        self.arcface_path = ROOT / "saved_models" / "simswap" / "arcface_model" / "arcface_checkpoint.tar"
        self.detector = None
        self.session = None
        self.net_arc = None
        self.embedding_map = None

    def load(self):
        if self._loaded:
            return
        if not self.model_path.exists():
            raise RuntimeError(f"ONNX model not found: {self.model_path}")
        if not self.arcface_path.exists():
            raise RuntimeError(f"ArcFace model not found: {self.arcface_path}")

        from dot.simswap.fs_model import legacy_simswap_import_path
        from dot.simswap.mediapipe.face_mesh import FaceMesh

        self.detector = FaceMesh(
            static_image_mode=False,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.55,
            min_tracking_confidence=0.5,
            mode="None",
        )

        import onnxruntime as ort
        available = ort.get_available_providers()
        providers = [p for p in ("CoreMLExecutionProvider", "CPUExecutionProvider") if p in available]
        providers = providers or available
        self.session = ort.InferenceSession(str(self.model_path), providers=providers)

        import torch
        device = get_device()
        with legacy_simswap_import_path():
            net_arc = torch.load(self.arcface_path, weights_only=False, map_location=device)
        self.net_arc = net_arc.to(device)
        self.net_arc.eval()

        from onnx import numpy_helper, load as onnx_load
        model = onnx_load(str(self.model_path))
        for initializer in model.graph.initializer:
            if initializer.name == "buff2fs":
                self.embedding_map = numpy_helper.to_array(initializer).astype(np.float32)
                break
        if self.embedding_map is None:
            raise RuntimeError("ONNX model missing buff2fs embedding map")
        self._loaded = True

    def _prepare_source(self, image_bytes: bytes) -> np.ndarray:
        import torch
        import torch.nn.functional as F

        arr = np.frombuffer(image_bytes, np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("Could not decode source image")

        result = self.detector.get(frame, 128)
        if result is None:
            raise HTTPException(status_code=400, detail="No face detected in source image.")

        crop = result[0][0]
        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        tensor = torch.from_numpy(rgb.transpose(2, 0, 1)).unsqueeze(0)
        mean = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
        std = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)
        device = get_device()
        tensor = ((tensor - mean) / std).to(device)
        tensor = F.interpolate(tensor, size=(112, 112), mode="bilinear", align_corners=False)

        with torch.no_grad():
            embedding = self.net_arc(tensor).detach().cpu().numpy().astype(np.float32)
        norm = np.linalg.norm(embedding, axis=1, keepdims=True).clip(min=1e-6)
        embedding = embedding / norm

        embedding = np.dot(embedding, self.embedding_map)
        embedding = embedding / np.linalg.norm(embedding, axis=1, keepdims=True).clip(min=1e-6)
        return embedding.astype(np.float32)

    def _swap_target(self, image_bytes: bytes, source_embedding: np.ndarray) -> bytes:
        arr = np.frombuffer(image_bytes, np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("Could not decode target image")

        result = self.detector.get(frame, 128)
        if result is None:
            raise HTTPException(status_code=400, detail="No face detected in target image.")

        output = frame
        crops, matrices = result
        for crop, matrix in zip(crops, matrices):
            rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB).astype(np.float32)
            target = ((rgb - 127.5) / 127.5).transpose(2, 0, 1)[None, ...].astype(np.float32)
            prediction = self.session.run(None, {"target": target, "source": source_embedding})[0]
            fake_rgb = prediction[0].transpose(1, 2, 0)
            fake_rgb = np.clip(fake_rgb * 127.5 + 127.5, 0, 255).astype(np.uint8)
            fake_bgr = cv2.cvtColor(fake_rgb, cv2.COLOR_RGB2BGR)

            height, width = frame.shape[:2]
            inverse = cv2.invertAffineTransform(matrix)
            warped = cv2.warpAffine(fake_bgr, inverse, (width, height), borderMode=cv2.BORDER_REFLECT)
            mask = np.zeros(fake_bgr.shape[:2], dtype=np.uint8)
            cx, cy = fake_bgr.shape[1] // 2, fake_bgr.shape[0] // 2
            cv2.ellipse(mask, (cx, cy), (int(fake_bgr.shape[1] * 0.43), int(fake_bgr.shape[0] * 0.50)),
                        0, 0, 360, 255, -1)
            mask = cv2.warpAffine(mask, inverse, (width, height), borderMode=cv2.BORDER_CONSTANT)
            blur = 25
            if blur % 2 == 0:
                blur += 1
            mask = cv2.GaussianBlur(mask, (blur, blur), 0)
            alpha = (mask.astype(np.float32) / 255.0)[:, :, None]
            output = (warped.astype(np.float32) * alpha + output.astype(np.float32) * (1.0 - alpha))
            output = np.clip(output, 0, 255).astype(np.uint8)

        _, encoded = cv2.imencode(".png", output)
        return encoded.tobytes()


class ExternalInferenceBackend:
    """Commercial backend bridge that avoids local NC model imports."""

    def __init__(self):
        self._loaded = False
        self.base_url = os.getenv("MORPHANUS_COMMERCIAL_BACKEND_URL", "").strip().rstrip("/")
        self.api_key = os.getenv("MORPHANUS_COMMERCIAL_BACKEND_KEY", "").strip()
        self._last_source = b""

    def load(self):
        if not self.base_url:
            raise RuntimeError(
                "MORPHANUS_COMMERCIAL_BACKEND_URL is required when "
                "MORPHANUS_INFERENCE_MODE=commercial_external"
            )
        self._loaded = True

    def _prepare_source(self, image_bytes: bytes) -> np.ndarray:
        # The external backend receives raw source/target bytes together.
        self._last_source = image_bytes
        return np.zeros((1, 1), dtype=np.float32)

    def _swap_target(self, image_bytes: bytes, _source_embedding: np.ndarray) -> bytes:
        import requests

        files = {
            "source": ("source.jpg", self._last_source, "image/jpeg"),
            "target": ("target.png", image_bytes, "image/png"),
        }
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        response = requests.post(
            f"{self.base_url}/swap",
            files=files,
            headers=headers,
            timeout=45,
        )
        if response.status_code >= 400:
            detail = response.text.strip() or "Commercial inference provider rejected request."
            raise HTTPException(status_code=502, detail=detail)
        return response.content


def get_backend() -> BackendProtocol:
    global _backend
    if _backend is None:
        mode = _inference_mode()
        if mode == "research_nc":
            _backend = InferenceBackend()
        elif mode == "commercial_external":
            _backend = ExternalInferenceBackend()
        else:
            raise RuntimeError(f"Unknown MORPHANUS_INFERENCE_MODE: {mode}")
    return _backend


@app.on_event("startup")
async def startup():
    import torch as _torch_module
    warn_nested_checkout(ROOT)
    print(f"[api] Device: {get_device()}")
    try:
        get_backend().load()
        print("[api] Backend loaded successfully")
    except Exception as e:
        print(f"[api] Backend load failed: {e}")


@app.get("/api/v1/health")
async def health():
    b = _backend
    loaded = b is not None and b._loaded
    keys = _load_keys()
    active_keys = sum(1 for k in keys.values() if k.get("active"))
    mode = _inference_mode()
    paid_mode = _paid_mode()
    return {
        "ok": True,
        "product": "morphanus-api",
        "commerceEnabled": paid_mode and mode == "commercial_external",
        "inference": {
            "status": "ready" if loaded else "loading",
            "backend": "onnx-inswapper" if mode == "research_nc" else mode,
            "device": get_device(),
            "mode": mode,
            "paidMode": paid_mode,
        },
        "accounts": {"totalKeys": len(keys), "activeKeys": active_keys},
    }


@app.post("/api/v1/swap", response_class=Response)
async def swap(source: UploadFile = File(...), target: UploadFile = File(...), api_key: str = Form(...)):
    import traceback
    try:
        _enforce_paid_inference_mode()
        _validate_key(api_key)

        source_bytes = await source.read()
        target_bytes = await target.read()
        if len(source_bytes) > 25 * 1024 * 1024:
            raise HTTPException(413, "Source exceeds 25MB limit")
        if len(target_bytes) > 25 * 1024 * 1024:
            raise HTTPException(413, "Target exceeds 25MB limit")

        backend = get_backend()
        if not backend._loaded:
            backend.load()

        job_id = f"mw_{int(time.time() * 1000):x}_{uuid.uuid4().hex[:6]}"
        source_embedding = backend._prepare_source(source_bytes)
        result_bytes = backend._swap_target(target_bytes, source_embedding)
        entry = _deduct_credit(api_key)

        _log_audit({
            "event": "swap_completed", "job_id": job_id,
            "email": entry.get("email", "unknown"), "plan": entry.get("plan", "unknown"),
            "source_bytes": len(source_bytes), "target_bytes": len(target_bytes),
            "uses_remaining": _credits_remaining(entry),
        })

        return Response(
            content=result_bytes, media_type="image/png",
            headers={
                "X-Job-Id": job_id, "X-Credits-Consumed": "1",
                "X-Credits-Remaining": _credits_remaining(entry),
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"[api] Swap error: {traceback.format_exc()}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run("api_server:app", host="127.0.0.1", port=8000, log_level="info")
