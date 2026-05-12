#!/usr/bin/env python3
"""Runtime safety checks for local DOT execution."""

from __future__ import annotations

import sys
from pathlib import Path


def detect_nested_checkout(root: Path) -> Path | None:
    """Return nested checkout path if a second git repo exists under root."""
    nested = root / "dot" / ".git"
    if nested.is_dir():
        return nested.parent
    return None


def warn_nested_checkout(root: Path) -> None:
    nested = detect_nested_checkout(root)
    if nested is None:
        return
    print(f"[dot] WARNING: nested repository detected at {nested}", file=sys.stderr)
    print("[dot] Run from only one checkout to avoid stale code paths.", file=sys.stderr)

