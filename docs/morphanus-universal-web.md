# Morphanus Universal Web Direction

Morphanus should move from a local conda-based toolkit to a zero-install browser product.

## Decision

The customer-facing product is `morphanus-web/`. The Python DOT runner remains a prototype and model lab, while `api_server.py` is the local API bridge for image exports.

## Launch Gate

Public paid launch stays frozen until:

- Commercial rights are documented for every model, weight, and copied source file.
- Hosted inference is deployed behind the same `/api/export` contract.
- Failed jobs return without consuming credits.
- Export metering is validated before live-session metering.
- The customer flow works from a clean browser without terminal setup.
- API paid mode is enabled only with `MORPHANUS_INFERENCE_MODE=commercial_external`.

## MVP Flow

1. Open the web app.
2. Upload a source image.
3. Grant camera permission.
4. Confirm consent.
5. Enter an active API key.
6. Create an image export.
7. Download the result.

## Native Apps

Tauri or another native wrapper is a later Pro path for OBS/virtual-camera workflows. It should wrap the same account and backend instead of becoming a second product.
