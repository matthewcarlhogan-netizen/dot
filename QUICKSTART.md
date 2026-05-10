# Quick Start

## Morphanus Web MVP

```bash
cd /Users/matt/dot/morphanus-web
npm install
npm run dev
```

Open `http://127.0.0.1:3000`.

Use the browser flow: upload source, start camera, confirm consent, create export.

Paid checkout is locked until hosted inference, metering, and commercial rights are ready.

## DOT Local Prototype

```bash
cd /Users/matt/dot
./run.sh --source data/source_face.webm --camera 1 --preset natural
```

Quit with `q`, Esc, or Ctrl-C.

Optional virtual camera:

```bash
./run.sh --source data/source_face.webm --camera 1 --preset natural --output both
```
