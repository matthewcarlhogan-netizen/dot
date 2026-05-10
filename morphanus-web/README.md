# Morphanus Web

Zero-install browser MVP for the universal Morphanus direction.

## Run

```bash
cd morphanus-web
npm install
npm run dev
```

Open `http://127.0.0.1:3000`.

## Verify

With the app running:

```bash
npm run smoke
```

## Current Scope

- Browser camera capture through `getUserMedia`.
- Source upload for image or short video.
- Explicit consent gate before export.
- Short-export API contract at `/api/export`.
- Browser-side demo export that composites the uploaded source into the captured camera frame with zero credits consumed.
- Paid checkout intentionally locked until commercial rights, hosted inference, metering, and retry-safe billing are implemented.

## Backend Contract

`POST /api/export` accepts multipart form data:

- `source`: uploaded image or video file.
- `frame`: captured browser preview frame.
- `consent`: must be `true`.

The route currently returns a completed stub job. Replace it with hosted GPU orchestration when the model stack is commercially cleared.
The current browser MVP creates the visible demo output client-side before posting the captured frame.
