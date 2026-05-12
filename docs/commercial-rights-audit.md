# Commercial Rights Audit

This audit is a release gate for paid Morphanus distribution.

## Current Finding

Paid launch is blocked until licensing is resolved. The repository-level license is BSD 3-Clause, but SimSwap model source files include CC BY-NC-SA 4.0 notices, including:

- `src/dot/simswap/models/fs_networks.py`
- `src/dot/simswap/models/fs_networks_512.py`

Do not sell packaged builds, hosted inference, use packs, or subscriptions until commercial use is cleared or the affected components are replaced.

## Required Before Charging

- Inventory every copied source file.
- Inventory every model weight and download URL.
- Record license, origin, commercial permission, attribution requirements, and redistribution permission.
- Replace any non-commercial component in the paid path.
- Keep proof beside the release artifact.

## Enforcement

Use the machine gate before any paid release:

```bash
python scripts/check_commercial_gate.py
```

The command reads `docs/license-manifest.csv` and fails if any component is blocked,
pending, or unknown for commercial rights in the paid path (`paid_path_required=yes`).
