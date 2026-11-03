#!/bin/sh
# Assist-mode scoring session: model-based shot tracking, recording, dataset extraction.
# Needs AI_SCORING_API_TOKEN and AI_SCORING_CAMERA_URL in the environment.
# Ctrl+C stops the companion; the script then extracts and prepares new dataset frames.
set -u
cd "$(dirname "$0")/.."
printf '%s\n' 'Starting shot-mode assist session; timing uncertainty is ASSUMED at 2000 ms.'
trap true INT
companion/.venv/bin/python -m ai_scoring.app \
 --data-directory companion/data \
 --mode assist --host 10.0.0.62 --port 8443 \
 --inference-enabled --inference-trigger shot \
 --calibration-file companion/data/calibration.json \
 --ball-model companion/data/models/ball-table-v8n.onnx \
 --inference-width 1280 --inference-height 720 \
 --sample-fps 10 --max-frame-gap-seconds 1 \
 --capture-timeout-seconds 10 --job-freshness-seconds 60 \
 --stable-seconds 0.5 --save-inference-frames \
 --recording-enabled --retention-seconds 7776000 \
 --recording-total-bytes 53687091200 --recording-min-free-bytes 21474836480 \
 --segment-seconds 60 --build-dataset \
 --capture-uncertainty-ms 2000 --max-capture-uncertainty-ms 2000
trap - INT
printf '%s\n' 'Companion stopped. Extracting and preparing new dataset frames...'
companion/.venv/bin/python -m ai_scoring.dataset --data-directory companion/data \
 --calibration-file companion/data/calibration.json || true
training/.venv/bin/python training/prepare_review.py || true
