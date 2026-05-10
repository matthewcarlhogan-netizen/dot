import json
import platform
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import yaml


def detect_camera(max_index: int = 5) -> int:
    try:
        import cv2

        for idx in range(max_index):
            cap = cv2.VideoCapture(idx)
            ok, _ = cap.read()
            cap.release()
            if ok:
                return idx
    except Exception:
        pass
    return 0


def validate_model_paths(config: Dict) -> Dict[str, bool]:
    keys = ["model_path", "parsing_model_path", "arcface_model_path", "checkpoints_dir"]
    return {k: (Path(v).exists() if v else False) for k, v in ((k, config.get(k)) for k in keys)}


def load_sample_workflow(config_file: Optional[str]) -> Dict:
    workflow = {
        "swap_type": "simswap",
        "source": "./data",
        "target": 0,
        "gpen_type": None,
        "gpen_path": "saved_models/gpen",
        "crop_size": 224,
        "show_fps": True,
        "use_gpu": False,
        "limit": 120,
    }
    if config_file and Path(config_file).exists():
        with open(config_file) as f:
            workflow.update(yaml.safe_load(f) or {})
    return workflow


def save_success_summary(settings: Dict, fps: float, output_dir: str = ".dot") -> str:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "settings": settings,
        "hardware_path": {
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "achieved_fps": round(fps, 2),
    }
    path = out / "last_success_summary.json"
    path.write_text(json.dumps(payload, indent=2))
    return str(path)


def export_share_setup(settings: Dict, output_dir: str = ".dot") -> str:
    redacted = {
        k: v
        for k, v in settings.items()
        if k not in {"source", "target", "save_folder", "model_path", "parsing_model_path", "arcface_model_path", "checkpoints_dir"}
    }
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "share_setup.yaml"
    path.write_text(yaml.safe_dump(redacted, sort_keys=True))
    return str(path)


def run_guided_demo(run_fn, settings: Dict) -> float:
    start = time.time()
    run_fn(**settings)
    elapsed = max(time.time() - start, 1e-6)
    frames = int(settings.get("limit") or 120)
    return frames / elapsed
