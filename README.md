# Morphanus / DOT

Morphanus is moving to a browser-first product. The customer-facing MVP lives in
`morphanus-web/`; the Python DOT runner remains a local prototype and model lab.

## Universal Web MVP

```bash
cd morphanus-web
npm install
npm run dev
```

Open:

```text
http://127.0.0.1:3000
```

The web MVP supports camera capture, source image upload, consent gating, API-key
billing, and a short image-export API contract. Public paid launch remains gated on
hosted inference and commercial-rights clearance.

Paid-mode guardrails in `api_server.py`:

- `MORPHANUS_PAID_MODE=1` blocks non-commercial research inference modes.
- Paid deployments must run one of:
  - `MORPHANUS_INFERENCE_MODE=commercial_inhouse` (self-hosted in-house inference)
  - `MORPHANUS_INFERENCE_MODE=commercial_external` (commercial provider)

See:

- `docs/morphanus-universal-web.md`
- `docs/commercial-rights-audit.md`

## DOT Local Prototype

Minimal local workflow:

```text
source image/video + physical webcam id -> swapped frames -> window or optional virtual camera
```

## Run

```bash
./run.sh --source data/source_face.webm --camera 1
```

Default output is the OpenCV window named `DOT - Live Deepfake`.

Useful options:

```bash
./run.sh --help
./run.sh --source data/source_face.jpg --camera 1
./run.sh --source data/source_face.webm --camera 1 --width 640 --height 480
./run.sh --source data/source_face.webm --camera 1 --prepare-source /tmp/prepared.png
```

`--backend simswap` is the installed default. To use the ONNX backend, place the model at `saved_models/onnx/inswapper_128_fp16.onnx` and set the environment variable `DOT_BACKEND=onnx` (note: the ONNX backend is experimental and requires additional dependencies).

`--output virtualcam` is not supported in this version. The output is always the OpenCV window. For virtual camera output, use a separate tool to capture the OpenCV window.

## Local Web Control

```bash
conda run -n dot python web.py
```

Open:

```text
http://127.0.0.1:7860
```

The page starts and stops the same local runner. It is a control surface, not a remote GPU service.

## First-Run Wizard

The upstream CLI/GUI first-run wizard is preserved for local prototype users.

This path mirrors the new first-run wizard behavior:

1. Keep your source assets in `./data` (default sample workflow path).
2. Start CLI wizard (auto camera detection + model validation + guided demo):

```bash
dot --source ./data --target 0 --wizard --show_fps
```

3. Optional: export a non-sensitive setup bundle for teammates:

```bash
dot --source ./data --target 0 --wizard --share_setup
```

4. Start GUI (`python -m dot.ui.ui`) and leave `first_run_wizard` enabled (default).
   - Wizard preloads source from `./data`
   - Auto-detects camera
   - Runs a short guided demo (default frame limit)
   - Writes local success summary to `.dot/last_success_summary.json`
   - Optional share bundle to `.dot/share_setup.yaml`

## Check

```bash
bash -n run.sh
conda run -n dot python -m compileall -q live.py health_check.py download_models.py src/dot
conda run -n dot python -m pytest -q
conda run -n dot python health_check.py
python scripts/check_commercial_gate.py
./run.sh --help
```

## Kept Runtime Assets

```text
data/source_face.webm
data/source_face.jpg
saved_models/simswap/
```
