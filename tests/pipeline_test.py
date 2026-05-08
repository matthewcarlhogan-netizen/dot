from pathlib import Path

import numpy as np
import pytest

import live


def test_presets_load():
    for path in live.PRESETS.values():
        config = live.load_config(path)
        assert config.get("swap_type", "simswap") == "simswap"


def test_natural_blend_modes():
    natural = live.load_config(live.PRESETS["natural"])
    natural_max = live.load_config(live.PRESETS["natural-max"])
    assert natural["natural_blend_mode"] == "alpha"
    assert natural_max["natural_blend_mode"] == "poisson"
    assert natural["natural_blend_strength"] < 1.0
    assert natural_max["natural_mask_blur"] >= natural["natural_mask_blur"]


def test_512_fallback(tmp_path):
    config = {
        "swap_type": "simswap",
        "crop_size": 512,
        "checkpoints_dir": str(tmp_path / "missing"),
    }
    assert live.ensure_supported_model_config(config)["crop_size"] == 224


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


def test_avatar_style_selects_avatar_backend():
    backend = live.make_backend("simswap", "avatar", {"detection_threshold": 0.5})
    assert isinstance(backend, live.AvatarBackend)
