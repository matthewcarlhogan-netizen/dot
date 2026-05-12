#!/usr/bin/env python3
"""
Benchmark ONNX pipeline with validation gate.
Measures FPS and exits with non-zero code if below target.
"""

import time
import cv2
import numpy as np
from pathlib import Path
import sys
sys.path.insert(0, str(Path('.') / 'src'))

from dot.simswap.mediapipe.face_mesh import FaceMesh
from dot.simswap.fs_model import legacy_simswap_import_path
from dot.commons.utils import get_device
import torch
import torch.nn.functional as F
import onnxruntime as ort
from onnx import numpy_helper, load as onnx_load

TARGET_FPS = 0.95
DURATION = 10  # seconds

def arcface_embedding(net_arc, crop_bgr, device):
    lab = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2LAB)
    light, a_chan, b_chan = cv2.split(lab)
    light = cv2.createCLAHE(clipLimit=1.6, tileGridSize=(8, 8)).apply(light)
    normalized = cv2.cvtColor(cv2.merge((light, a_chan, b_chan)), cv2.COLOR_LAB2BGR)
    rgb = cv2.cvtColor(normalized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    tensor = torch.from_numpy(rgb.transpose(2, 0, 1)).unsqueeze(0)
    mean = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
    std = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)
    tensor = ((tensor - mean) / std).to(device)
    tensor = F.interpolate(tensor, size=(112, 112), mode='bilinear', align_corners=False)
    with torch.no_grad():
        embedding = net_arc(tensor).detach().cpu().numpy().astype(np.float32)
    norm = np.linalg.norm(embedding, axis=1, keepdims=True).clip(min=1e-6)
    return embedding / norm

def soft_paste(frame, patch, matrix, blur=21):
    height, width = frame.shape[:2]
    inverse = cv2.invertAffineTransform(matrix)
    warped = cv2.warpAffine(patch, inverse, (width, height), borderMode=cv2.BORDER_REFLECT)
    mask = np.zeros(patch.shape[:2], dtype=np.uint8)
    cv2.ellipse(mask, (patch.shape[1] // 2, patch.shape[0] // 2), (int(patch.shape[1] * 0.43), int(patch.shape[0] * 0.50)), 0, 0, 360, 255, -1)
    mask = cv2.warpAffine(mask, inverse, (width, height), borderMode=cv2.BORDER_CONSTANT)
    if blur > 1:
        if blur % 2 == 0:
            blur += 1
        mask = cv2.GaussianBlur(mask, (blur, blur), 0)
    alpha = (mask.astype(np.float32) / 255.0)[:, :, None]
    blended = warped.astype(np.float32) * alpha + frame.astype(np.float32) * (1.0 - alpha)
    return np.clip(blended, 0, 255).astype(np.uint8)

def main():
    print(f"ONNX Pipeline Benchmark (target: >= {TARGET_FPS} FPS, duration: {DURATION}s)")
    print("=" * 60)

    ROOT = Path('.')
    model_path = ROOT / 'saved_models' / 'onnx' / 'inswapper_128_fp16.onnx'
    arcface_path = ROOT / 'saved_models' / 'simswap' / 'arcface_model' / 'arcface_checkpoint.tar'
    source_path = ROOT / 'data' / 'source_face.webm'

    # Session options with environment variable overrides
    sess_options = ort.SessionOptions()
    sess_options.intra_op_num_threads = int(os.getenv("DOT_ORT_INTRA_THREADS", "8"))
    sess_options.inter_op_num_threads = int(os.getenv("DOT_ORT_INTER_THREADS", "1"))
    sess_options.enable_mem_pattern = True
    sess_options.enable_mem_reuse = True
    sess_options.enable_cpu_mem_arena = True

    env_provider = os.getenv("DOT_ORT_PROVIDERS")
    available = ort.get_available_providers()
    providers = [p for p in ('CoreMLExecutionProvider', 'CPUExecutionProvider') if p in available]
    if env_provider and env_provider in available:
        providers = [env_provider]
        print(f"Using DOT_ORT_PROVIDERS: {env_provider}")
    elif not available:
        providers = available

    session = ort.InferenceSession(str(model_path), sess_options, providers=providers)
    print(f"Providers: {', '.join(session.get_providers())}")
    print(f"Intra threads: {sess_options.intra_op_num_threads}")
    print(f"Inter threads: {sess_options.inter_op_num_threads}")

    device = get_device()
    with legacy_simswap_import_path():
        net_arc = torch.load(arcface_path, weights_only=False, map_location=device)
    net_arc = net_arc.to(device)
    net_arc.eval()

    model = onnx_load(str(model_path))
    for initializer in model.graph.initializer:
        if initializer.name == 'buff2fs':
            embedding_map = numpy_helper.to_array(initializer).astype(np.float32)
            break

    # Prepare source
    cap = cv2.VideoCapture(str(source_path))
    ok, frame = cap.read()
    if not ok:
        print("ERROR: Cannot read source")
        return 1
    cap.release()

    detector = FaceMesh(static_image_mode=True, max_num_faces=1, refine_landmarks=True, min_detection_confidence=0.5, mode='None')
    result = detector.get(frame, 128)
    if result is None:
        print("ERROR: No face in source")
        return 1
    crop, _ = result
    source_crop = crop[0]

    embedding = arcface_embedding(net_arc, source_crop, device)
    embedding = np.dot(embedding, embedding_map)
    embedding = embedding / np.linalg.norm(embedding, axis=1, keepdims=True).clip(min=1e-6)
    source_embedding = embedding.astype(np.float32)

    # Processing detector
    detector = FaceMesh(static_image_mode=False, max_num_faces=1, refine_landmarks=True, min_detection_confidence=0.55, min_tracking_confidence=0.5, mode='None')

    input_names = [input.name for input in session.get_inputs()]
    feed = {name: arr for name, arr in zip(input_names, [np.zeros((1, 3, 128, 128), dtype=np.float32), source_embedding])}

    print(f"\nRunning for {DURATION} seconds...")

    frame_count = 0
    start = time.perf_counter()
    end_time = start + DURATION

    while time.perf_counter() < end_time:
        result = detector.get(frame, 128)
        if result is not None:
            crops, matrices = result
            for crop, matrix in zip(crops, matrices):
                feed['target'] = ((cv2.cvtColor(crop, cv2.COLOR_BGR2RGB).astype(np.float32) - 127.5) / 127.5).transpose(2, 0, 1)[None, ...].astype(np.float32)
                prediction = session.run(None, feed)[0]
                fake_rgb = prediction[0].transpose(1, 2, 0)
                fake_rgb = np.clip(fake_rgb * 127.5 + 127.5, 0, 255).astype(np.uint8)
                fake_bgr = cv2.cvtColor(fake_rgb, cv2.COLOR_RGB2BGR)
                _ = soft_paste(frame, fake_bgr, matrix, blur=25)
        frame_count += 1

    elapsed = time.perf_counter() - start
    fps = frame_count / elapsed if elapsed > 0 else 0

    print(f"\nResults: {frame_count} frames in {elapsed:.2f}s = {fps:.2f} FPS")

    if fps >= TARGET_FPS:
        print(f"SUCCESS: {fps:.2f} FPS >= {TARGET_FPS} FPS target")
        return 0
    else:
        print(f"FAILED: {fps:.2f} FPS < {TARGET_FPS} FPS target")
        return 1

if __name__ == "__main__":
    import os
    sys.exit(main())