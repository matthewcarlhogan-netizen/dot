from pathlib import Path

import numpy as np
import pytest

import live


def test_presets_load():
    config = live.load_config(live.HIGHEST_QUALITY_PRESET)
    assert config.get("swap_type", "simswap") == "simswap"


def test_natural_blend_modes():
    natural_max = live.load_config(live.HIGHEST_QUALITY_PRESET)
    assert natural_max["natural_blend_mode"] == "poisson"
    assert natural_max["natural_blend_strength"] >= 0.9
    assert natural_max["natural_mask_blur"] >= 25


def test_512_checkpoint_required(tmp_path):
    config = {
        "swap_type": "simswap",
        "crop_size": 512,
        "checkpoints_dir": str(tmp_path / "missing"),
    }
    with pytest.raises(RuntimeError, match="requires the 512px SimSwap checkpoint"):
        live.ensure_highest_quality_model_config(config)


def test_512_checkpoint_valid(tmp_path):
    checkpoint = tmp_path / "checkpoints" / "512" / "550000_net_G.pth"
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_bytes(b"ok")
    config = {
        "swap_type": "simswap",
        "crop_size": 512,
        "checkpoints_dir": str(tmp_path / "checkpoints"),
    }
    assert live.ensure_highest_quality_model_config(config) == config


def test_virtualcam_missing_is_clear(monkeypatch):
    original_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "pyvirtualcam":
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    with pytest.raises(RuntimeError, match="Virtual camera output requires pyvirtualcam"):
        live.VirtualCameraSink(640, 480)


def test_onnx_missing_model_is_clear(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "ROOT", Path(tmp_path))
    with pytest.raises(RuntimeError, match="inswapper_128_fp16.onnx"):
        live.OnnxBackend()


def test_source_crop_preparation_preserves_shape():
    crop = np.full((128, 128, 3), 80, dtype=np.uint8)
    crop[:32, :, :] = 230
    crop[:, 40:88, 1] = 120
    prepared = live.prepare_source_crop(crop)
    assert prepared.shape == crop.shape
    assert prepared.dtype == np.uint8
    assert prepared.std() > 0


def test_highest_quality_mode_enforces_preset():
    class Args:
        preset = "natural"

    args = live.enforce_highest_quality_mode(Args())
    assert args.preset == "natural-max"


def test_parse_args_exposes_single_function_surface(monkeypatch):
    monkeypatch.setattr("sys.argv", ["live.py", "--source", "data/source_face.webm", "--camera", "1"])
    args = live.parse_args()
    assert hasattr(args, "source")
    assert hasattr(args, "camera")
    assert hasattr(args, "width")
    assert hasattr(args, "height")
    assert hasattr(args, "prepare_source")
    assert hasattr(args, "source_cache_dir")
    assert hasattr(args, "debug")
    assert not hasattr(args, "backend")
    assert not hasattr(args, "style")
    assert not hasattr(args, "preset")
    assert not hasattr(args, "output")


def test_prepared_source_cache_path_changes_with_mtime(tmp_path):
    source = tmp_path / "source.jpg"
    source.write_bytes(b"abc")
    cache = tmp_path / "cache"
    first = live.prepared_source_cache_path(source, cache)
    source.write_bytes(b"abcd")
    second = live.prepared_source_cache_path(source, cache)
    assert first != second


def test_resolve_source_for_backend_uses_cache(tmp_path):
    source = tmp_path / "source.jpg"
    source.write_bytes(b"abc")
    cache = tmp_path / "cache"
    cached = live.prepared_source_cache_path(source, cache)
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(b"png")
    resolved = live.resolve_source_for_backend(source, prepare_source=True, cache_dir=cache)
    assert resolved == cached


def test_resolve_source_for_backend_respects_disable(tmp_path):
    source = tmp_path / "source.jpg"
    source.write_bytes(b"abc")
    cache = tmp_path / "cache"
    resolved = live.resolve_source_for_backend(source, prepare_source=False, cache_dir=cache)
    assert resolved == source


def test_detect_source_face_raises_when_missing(monkeypatch):
    class FakeDetector:
        def __init__(self, *args, **kwargs):
            pass

        def get(self, frame, size):
            return None

    monkeypatch.setattr(live, "FaceMesh", FakeDetector)
    frame = np.zeros((64, 64, 3), dtype=np.uint8)
    with pytest.raises(RuntimeError, match="No face detected"):
        live.detect_source_face(frame, size=64, detection_threshold=0.5)


def test_load_source_face_crop_uses_picker(monkeypatch, tmp_path):
    source = tmp_path / "source.webm"
    source.write_bytes(b"fake")
    picked = np.full((64, 64, 3), 140, dtype=np.uint8)

    class FakeDetector:
        def __init__(self, *args, **kwargs):
            pass

        def get(self, frame, size):
            crop = np.full((size, size, 3), 200, dtype=np.uint8)
            mat = np.eye(2, 3, dtype=np.float32)
            return [crop], [mat]

    monkeypatch.setattr(live, "pick_source_frame_with_face", lambda s, size: picked)
    monkeypatch.setattr(live, "FaceMesh", FakeDetector)
    crop = live.load_source_face_crop(source, size=32, detection_threshold=0.5)
    assert crop.shape == (32, 32, 3)
