# Morphanus Web

Zero-install browser MVP for the universal Morphanus direction.

## Run

```bash
cd morphanus-web
npm install
npm run dev
```

Open `http://127.0.0.1:3000`.

## Current Scope

- Browser camera capture through `getUserMedia`.
- Source image upload for the current export path.
- Explicit consent gate before export.
- API-key-gated export through `/api/export`.
- Local ONNX inswapper inference through `MORPHANUS_API_URL` or `http://127.0.0.1:8000`.
- Credits are deducted only after a successful generated image response.

## Backend Contract

`POST /api/export` accepts multipart form data:

- `source`: uploaded image file.
- `frame`: captured browser preview frame.
- `consent`: must be `true`.
- `api_key`: active Morphanus API key.

The route proxies to `POST /api/v1/swap` on the Python API server and returns a PNG plus credit headers.
