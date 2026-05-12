# M2 8GB Guide

Use the `dot` conda environment and keep other apps closed for the 512px preset (natural-max, highest quality).

```bash
./run.sh --source data/source_face.webm --camera 1
```

Notes:
- The preset is fixed to `natural-max` (highest quality) for the local prototype.
- The output is always the OpenCV window named `DOT - Live Deepfake`.
- To prepare the source identity (without running the live swap), use `--prepare-source <output_path>`.
- Adjust window size with `--width` and `--height` (default 640x480).
