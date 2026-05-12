from pathlib import Path

import runtime_guard


def test_detect_nested_checkout_none(tmp_path):
    assert runtime_guard.detect_nested_checkout(tmp_path) is None


def test_detect_nested_checkout_found(tmp_path):
    nested_git = tmp_path / "dot" / ".git"
    nested_git.mkdir(parents=True)
    detected = runtime_guard.detect_nested_checkout(tmp_path)
    assert detected == tmp_path / "dot"

