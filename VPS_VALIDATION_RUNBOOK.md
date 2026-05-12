# VPS Validation Runbook

## Purpose
This runbook provides step-by-step procedures for validating the DOT Face-Swap Engine on a VPS (Virtual Private Server). It covers health checks, end-to-end functionality, credit management, and failure recovery.

---

## Prerequisites

### Server Requirements
- Linux VPS (Ubuntu 20.04/22.04 recommended)
- Minimum 8GB RAM, 2+ CPU cores
- Python 3.10+ with conda (or equivalent virtual environment)
- GPU access (optional, for better performance)

### Environment Setup
```bash
# Clone/setup DOT (if not already done)
cd /opt/dot  # or your preferred location

# Activate environment
source ~/miniforge3/etc/profile.d/conda.sh
conda activate dot

# Verify installation
python -c "import cv2, torch, mediapipe, onnxruntime; print('All dependencies OK')"
```

---

## 1. Health Check Validation

### Procedure
```bash
# Run health check
python health_check.py

# Expected output:
# [OK] macOS/Linux
# [OK] Python 3.10+
# [OK] PyTorch (MPS/CUDA/CPU)
# [OK] OpenCV
# [OK] MediaPipe FaceMesh
# [OK] live.py
# [OK] run.sh
# [OK] configs/*.yaml
# [OK] saved_models/**/*
# [OK] data/source_face.*
# Ready: ./run.sh --source data/source_face.webm --camera 1
```

### Expected Results
- All checks show `[OK]`
- Final line shows "Ready: ./run.sh ..."
- Exit code: 0

### Troubleshooting
| Issue | Solution |
|-------|----------|
| MediaPipe missing | `conda install mediapipe` or use environment-apple-m2.yaml |
| Models missing | Run `python download_models.py` |
| Config errors | Check configs/*.yaml exist and are valid |

---

## 2. API Server Validation

### Starting the API Server
```bash
# Start API server (in background)
nohup python api_server.py > api.log 2>&1 &
API_PID=$!
echo "API started with PID: $API_PID"

# Wait for startup
sleep 5

# Check health endpoint
curl -s http://localhost:8000/api/v1/health | jq .
```

### Expected Health Response
```json
{
  "ok": true,
  "product": "morphanus-api",
  "commerceEnabled": false,
  "inference": {
    "status": "ready",
    "backend": "onnx-inswapper",
    "device": "cpu",
    "mode": "research_nc",
    "paidMode": false
  },
  "accounts": {
    "totalKeys": 0,
    "activeKeys": 0
  }
}
```

### Validation Checklist
- [ ] GET `/api/v1/health` returns 200
- [ ] `status` is "ready" (not "loading")
- [ ] `commerceEnabled` matches MORPHANUS_PAID_MODE setting
- [ ] `backend` matches expected inference mode

---

## 3. End-to-End Swap Validation

### Test 1: Basic Swap (No API Key)
```bash
# Upload and swap using test images
curl -X POST http://localhost:8000/api/v1/swap \
  -F "source=@data/source_face.jpg" \
  -F "target=@data/target_face.jpg" \
  -F "api_key=TEST-KEY" \
  --output result.png -w "\nHTTP Code: %{http_code}\n"
```

### Test 2: Validate Response
```bash
# Check result is valid PNG
file result.png
# Expected: result.png: PNG image data

# Check headers for credit info
curl -sI -X POST http://localhost:8000/api/v1/swap \
  -F "source=@data/source_face.jpg" \
  -F "target=@data/target_face.jpg" \
  -F "api_key=TEST-KEY" | grep -E "(X-|HTTP)"
```

### Expected Results
| Test | Expected |
|------|----------|
| HTTP Status | 200 (or appropriate error) |
| Content-Type | image/png |
| X-Job-Id | Present (hex string) |
| X-Credits-Consumed | "1" (if paid mode) |
| X-Credits-Remaining | Decremented correctly |

---

## 4. Credit System Validation

### Setup Test Keys
```bash
# Create test keys database
mkdir -p vps_portal
cat > vps_portal/keys.json << 'EOF'
{
  "TEST-KEY-1": {
    "active": true,
    "email": "test@example.com",
    "plan": "uses_5",
    "uses_allowed": 5,
    "uses_remaining": 5
  },
  "TEST-KEY-EMPTY": {
    "active": true,
    "email": "empty@example.com",
    "plan": "uses_2",
    "uses_allowed": 2,
    "uses_remaining": 0
  },
  "TEST-KEY-INACTIVE": {
    "active": false,
    "email": "inactive@example.com",
    "plan": "uses_10",
    "uses_allowed": 10,
    "uses_remaining": 10
  }
}
EOF
```

### Validation Tests
```bash
# Test 1: Valid key with credits (should succeed)
curl -s -X POST ... -F "api_key=TEST-KEY-1" | jq .
# Expected: 200, image returned, credits decremented

# Test 2: Empty credits (should fail with 402)
curl -s -w "%{http_code}" -X POST ... -F "api_key=TEST-KEY-EMPTY"
# Expected: 402

# Test 3: Inactive key (should fail with 403)
curl -s -w "%{http_code}" -X POST ... -F "api_key=TEST-KEY-INACTIVE"
# Expected: 403

# Test 4: Invalid key format (should fail with 401)
curl -s -w "%{http_code}" -X POST ... -F "api_key=INVALID"
# Expected: 401
```

### Subscription Sync Check
```bash
# After a successful swap, verify subscription file is updated
cat vps_portal/subscriptions.json | jq '.customers["test@example.com"]'
# Should show updated uses_remaining
```

---

## 5. Negative-Path Tests

### Oversized Payload
```bash
# Create 30MB test file (over 25MB limit)
dd if=/dev/urandom of=oversized.jpg bs=1M count=30 2>/dev/null

curl -s -w "%{http_code}" -X POST http://localhost:8000/api/v1/swap \
  -F "source=@oversized.jpg" \
  -F "target=@data/target_face.jpg" \
  -F "api_key=TEST-KEY-1"
# Expected: 413
```

### No Face in Image
```bash
# Use an image without a face
curl -s -w "%{http_code}" -X POST http://localhost:8000/api/v1/swap \
  -F "source=@data/no_face_image.jpg" \
  -F "target=@data/target_face.jpg" \
  -F "api_key=TEST-KEY-1"
# Expected: 400
```

### Invalid Image Format
```bash
# Send non-image data
echo "not an image" > /tmp/bad.txt
curl -s -w "%{http_code}" -X POST http://localhost:8000/api/v1/swap \
  -F "source=@/tmp/bad.txt" \
  -F "target=@data/target_face.jpg" \
  -F "api_key=TEST-KEY-1"
# Expected: 500 or 400
```

### Upstream Timeout Simulation
```bash
# Set MORPHANUS_COMMERCIAL_BACKEND_URL to unreachable server
MORPHANUS_INFERENCE_MODE=commercial_external \
MORPHANUS_COMMERCIAL_BACKEND_URL=http://10.255.255.1:9999 \
MORPHANUS_PAID_MODE=1 \
python api_server.py &

# Attempt swap - should timeout gracefully
curl -s -w "%{http_code}" -X POST ... -F "api_key=TEST-KEY-1"
# Expected: 502 (Bad Gateway)
```

---

## 6. Restart Recovery Test

### Procedure
```bash
# 1. Start fresh
rm -f vps_portal/*.json vps_portal/*.jsonl

# 2. Initialize with test data
cat > vps_portal/keys.json << 'EOF'
{
  "RECOVERY-TEST": {
    "active": true,
    "email": "recovery@test.com",
    "plan": "uses_3",
    "uses_allowed": 3,
    "uses_remaining": 3
  }
}
EOF

# 3. Start API server
python api_server.py &
API_PID=$!
sleep 3

# 4. Perform 2 swaps
for i in 1 2; do
  curl -s -X POST http://localhost:8000/api/v1/swap \
    -F "source=@data/source_face.jpg" \
    -F "target=@data/target_face.jpg" \
    -F "api_key=RECOVERY-TEST" > /dev/null
  echo "Swap $i completed"
done

# 5. Check remaining credits (should be 1)
curl -s http://localhost:8000/api/v1/health | jq '.accounts'
# Expected: "activeKeys": 1 (if using same key for counting)

# 6. Stop server
kill $API_PID
sleep 2

# 7. Restart server
python api_server.py &
API_PID=$!
sleep 3

# 8. Verify health
curl -s http://localhost:8000/api/v1/health | jq .
# Expected: status "ready", all previous state preserved

# 9. Perform another swap (should work with remaining credit)
curl -s -X POST http://localhost:8000/api/v1/swap \
  -F "source=@data/source_face.jpg" \
  -F "target=@data/target_face.jpg" \
  -F "api_key=RECOVERY-TEST" -o /dev/null -w "HTTP: %{http_code}\n"
# Expected: 200

# 10. Attempt swap with no credits remaining (should fail)
curl -s -X POST http://localhost:8000/api/v1/swap \
  -F "source=@data/source_face.jpg" \
  -F "target=@data/target_face.jpg" \
  -F "api_key=RECOVERY-TEST" -w "HTTP: %{http_code}\n"
# Expected: 402

echo "Recovery test complete!"
```

---

## 7. Performance Validation

### Quick Benchmark
```bash
# Run 10-second performance test
python -c "
import time, numpy as np, onnxruntime as ort
from pathlib import Path

m = Path('saved_models/onnx/inswapper_128_fp16.onnx')
sess_options = ort.SessionOptions()
sess_options.intra_op_num_threads = int(os.getenv('DOT_ORT_INTRA_THREADS', 8))
sess_options.inter_op_num_threads = int(os.getenv('DOT_ORT_INTER_THREADS', 1))
sess = ort.InferenceSession(str(m), sess_options)

tn = np.random.randn(1,3,128,128).astype(np.float32)
sn = np.random.randn(1,512).astype(np.float32)
sn = sn / np.linalg.norm(sn)
inp = {sess.get_inputs()[0].name: tn, sess.get_inputs()[1].name: sn}

sess.run(None, inp)  # warmup
t = time.perf_counter()
for _ in range(30):
    sess.run(None, inp)
fps = 30 / (time.perf_counter() - t)
print(f'ONNX FPS: {fps:.2f}')
print('PASS' if fps >= 0.95 else 'FAIL - needs optimization')
"
```

### Expected Results
| Metric | Minimum | Target |
|--------|---------|--------|
| ONNX inference FPS | ≥0.90 | ≥0.95 |
| API response time (p50) | <5s | <3s |
| API response time (p99) | <15s | <10s |
| Memory usage | <3GB | <2.5GB |

---

## 8. Log Monitoring

### Key Log Patterns
```bash
# Monitor API errors
tail -f api.log | grep -E "(ERROR|Exception|500|502|503)"

# Monitor swap performance  
tail -f api.log | grep "swap_completed"

# Monitor memory usage
watch -n 5 'ps aux | grep "python.*api" | grep -v grep'

# Check audit log for anomalies
cat vps_portal/audit_log.jsonl | jq 'select(.event=="swap_completed") | .uses_remaining' | sort | uniq -c
```

### Common Issues and Solutions
| Log Pattern | Issue | Solution |
|-------------|-------|----------|
| `CUDA error` | GPU memory exhausted | Reduce batch size, restart service |
| `onnxruntime.*error` | Model loading failure | Verify model file integrity |
| `face not detected` | Input quality issue | Check source image requirements |
| `402.*No credits` | Credit exhaustion | Replenish credits via keys.json |
| `502.*timeout` | Backend timeout | Check upstream provider, increase timeout |
| `memory.*available` | Low system memory | Close other applications |

---

## 9. Checklist Summary

Run this complete checklist after any deployment or configuration change:

- [ ] Health endpoint returns 200 with "ready" status
- [ ] Successful swap returns 200 with valid PNG
- [ ] Credit deduction is exactly 1 per successful swap
- [ ] Zero-credit key returns 402
- [ ] Invalid key returns 401
- [ ] Inactive key returns 403
- [ ] Oversized payload returns 413
- [ ] No-face image returns 400
- [ ] Service restart preserves state
- [ ] Audit log entries are created for each swap
- [ ] Performance meets minimum threshold (≥0.90 FPS)
- [ ] No memory leaks detected after 1 hour of operation

---

*Last updated: Implementation phase 1 complete*
*Performance optimization pending (target: ≥0.95 FPS)*