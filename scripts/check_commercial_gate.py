#!/usr/bin/env python3
"""Fail-fast commercial rights gate for paid Morphanus release."""

from __future__ import annotations

import csv
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "license-manifest.csv"

REQUIRED_COLUMNS = [
    "component",
    "path_or_identifier",
    "origin",
    "license",
    "commercial_use_allowed",
    "redistribution_allowed",
    "attribution_required",
    "status",
    "paid_path_required",
    "proof_or_notes",
]


def fail(msg: str) -> int:
    print(f"[commercial-gate] FAIL: {msg}")
    return 1


def main() -> int:
    if not MANIFEST.exists():
        return fail(f"missing manifest: {MANIFEST}")

    with MANIFEST.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            return fail("manifest has no header row")
        missing = [c for c in REQUIRED_COLUMNS if c not in reader.fieldnames]
        if missing:
            return fail(f"manifest missing required columns: {', '.join(missing)}")

        rows = list(reader)
        if not rows:
            return fail("manifest has no component rows")

    blocked = []
    unknown = []
    unresolved = []

    for row in rows:
        label = row["component"].strip() or row["path_or_identifier"].strip()
        commercial = row["commercial_use_allowed"].strip().lower()
        status = row["status"].strip().lower()
        paid_path_required = row["paid_path_required"].strip().lower()

        if commercial not in {"yes", "no", "unknown"}:
            unknown.append(f"{label}: invalid commercial_use_allowed='{commercial}'")
        if status not in {"approved", "blocked", "replace", "pending"}:
            unknown.append(f"{label}: invalid status='{status}'")
        if paid_path_required not in {"yes", "no"}:
            unknown.append(f"{label}: invalid paid_path_required='{paid_path_required}'")

        if paid_path_required != "yes":
            continue

        if commercial == "no" or status in {"blocked", "replace"}:
            blocked.append(label)
        if commercial == "unknown" or status == "pending":
            unresolved.append(label)

    if unknown:
        return fail("invalid manifest values:\n- " + "\n- ".join(unknown))
    if blocked:
        return fail(
            "non-commercial or blocked components still present:\n- "
            + "\n- ".join(blocked)
        )
    if unresolved:
        return fail(
            "components still pending rights confirmation:\n- "
            + "\n- ".join(unresolved)
        )

    print("[commercial-gate] PASS: all manifest entries approved for paid distribution")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
