import asyncio
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

import api_server


API_KEY = "DOT-TEST-KEY"


class FakeBackend:
    def __init__(self, fail_prepare=False, fail_swap=False):
        self._loaded = True
        self.fail_prepare = fail_prepare
        self.fail_swap = fail_swap

    def load(self):
        self._loaded = True

    def _prepare_source(self, _image_bytes):
        if self.fail_prepare == "decode":
            raise ValueError("Could not decode source image")
        if self.fail_prepare:
            raise HTTPException(status_code=400, detail="No face detected in source image.")
        return np.zeros((1, 512), dtype=np.float32)

    def _swap_target(self, _image_bytes, _source_embedding):
        if self.fail_swap:
            raise RuntimeError("backend failed")
        return b"png-bytes"


@pytest.fixture()
def billing_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(api_server, "VPS_DIR", tmp_path)
    expires = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    keys = {
        API_KEY: {
            "active": True,
            "email": "buyer@example.com",
            "expires_at": expires,
            "plan": "uses_2",
            "uses_allowed": 2,
            "uses_remaining": 2,
        },
        "DOT-EMPTY": {
            "active": True,
            "email": "empty@example.com",
            "expires_at": expires,
            "plan": "uses_2",
            "uses_allowed": 2,
            "uses_remaining": 0,
        },
    }
    subs = {
        "customers": {
            "buyer@example.com": {
                "email": "buyer@example.com",
                "key": API_KEY,
                "plan": "uses_2",
                "uses_remaining": 2,
            }
        },
        "invoices": {},
    }
    (tmp_path / "keys.json").write_text(json.dumps(keys))
    (tmp_path / "subscriptions.json").write_text(json.dumps(subs))
    return tmp_path


def uses_remaining(path: Path, api_key: str = API_KEY) -> int:
    return json.loads((path / "keys.json").read_text())[api_key]["uses_remaining"]


def upload(name: str, content: bytes) -> UploadFile:
    return UploadFile(filename=name, file=io.BytesIO(content))


def run_swap(api_key=API_KEY, source=b"source", target=b"target"):
    return asyncio.run(
        api_server.swap(
            source=upload("source.jpg", source),
            target=upload("target.png", target),
            api_key=api_key,
        )
    )


def test_invalid_key_does_not_deduct(billing_dir):
    with pytest.raises(HTTPException) as exc:
        run_swap(api_key="DOT-BAD")
    assert exc.value.status_code == 401
    assert uses_remaining(billing_dir) == 2


def test_no_credits_returns_402(billing_dir):
    with pytest.raises(HTTPException) as exc:
        run_swap(api_key="DOT-EMPTY")
    assert exc.value.status_code == 402
    assert uses_remaining(billing_dir, "DOT-EMPTY") == 0


def test_oversized_source_does_not_deduct(billing_dir):
    with pytest.raises(HTTPException) as exc:
        run_swap(source=b"x" * (25 * 1024 * 1024 + 1))
    assert exc.value.status_code == 413
    assert uses_remaining(billing_dir) == 2


def test_no_face_source_does_not_deduct(billing_dir, monkeypatch):
    monkeypatch.setattr(api_server, "get_backend", lambda: FakeBackend(fail_prepare=True))
    with pytest.raises(HTTPException) as exc:
        run_swap()
    assert exc.value.status_code == 400
    assert uses_remaining(billing_dir) == 2


def test_bad_image_does_not_deduct(billing_dir, monkeypatch):
    monkeypatch.setattr(api_server, "get_backend", lambda: FakeBackend(fail_prepare="decode"))
    with pytest.raises(HTTPException) as exc:
        run_swap(source=b"not-an-image")
    assert exc.value.status_code == 500
    assert uses_remaining(billing_dir) == 2


def test_backend_failure_does_not_deduct(billing_dir, monkeypatch):
    monkeypatch.setattr(api_server, "get_backend", lambda: FakeBackend(fail_swap=True))
    with pytest.raises(HTTPException) as exc:
        run_swap()
    assert exc.value.status_code == 500
    assert uses_remaining(billing_dir) == 2


def test_success_deducts_exactly_one_credit(billing_dir, monkeypatch):
    monkeypatch.setattr(api_server, "get_backend", lambda: FakeBackend())
    response = run_swap()
    assert response.status_code == 200
    assert response.body == b"png-bytes"
    assert response.headers["x-credits-consumed"] == "1"
    assert response.headers["x-credits-remaining"] == "1"
    assert uses_remaining(billing_dir) == 1

    subs = json.loads((billing_dir / "subscriptions.json").read_text())
    assert subs["customers"]["buyer@example.com"]["uses_remaining"] == 1
