# Morphanus Universal Web Direction

Morphanus should move from a local conda-based toolkit to a zero-install browser product.

## Decision

The customer-facing product is `morphanus-web/`. The Python DOT runner remains a prototype and model lab until the hosted inference backend is ready.

## Launch Gate

Paid launch stays frozen until:

- Commercial rights are documented for every model, weight, and copied source file.
- Hosted inference replaces the stub `/api/export` route.
- Failed jobs return without consuming credits.
- Export metering is implemented before live-session metering.
- The customer flow works from a clean browser without terminal setup.

## Remote Demo

The local app can be exposed temporarily through a tunnel for remote testing. Use production mode for this demo:

```bash
cd /Users/matt/dot/morphanus-web
npm run build
npm run start -- --port 3000
```

Then tunnel `127.0.0.1:3000` with the available tunnel provider. Do not add payment, uploads to third-party storage, or public gallery behavior to the remote demo.

## MVP Flow

1. Open the web app.
2. Upload a source image or short video.
3. Grant camera permission.
4. Confirm consent.
5. Create a short export that composites the uploaded source into the captured camera frame.
6. Download the result.

## Native Apps

Tauri or another native wrapper is a later Pro path for OBS/virtual-camera workflows. It should wrap the same account and backend instead of becoming a second product.
