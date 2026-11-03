# Shot-mode table tracking (experimental)

Enabled with `--inference-trigger shot`. History of approved changes (user-authorized): direct implementation 2026-10-13; on 2026-10-29 the multi-frame VLM shot flow was replaced by settled-table inventory comparison, then the VLM reader by local colour-blob detection with mid-frame starts, then motion-gated reading by continuous tracking. Superseded options were removed rather than kept for compatibility.

## Behavior

Every sampled frame is read by `domain/ball_detection.py` (no model; milliseconds per frame). Ball-sized non-cloth blobs inside the calibrated pocket outline, excluding pocket mouths, are labelled by colour; touching reds are counted by area. A large blob over the cloth (person, cue, object) makes the frame occluded; large blobs on the rail edge are ignored; a duplicate colour or more than 15 reds is uncertain. Colour thresholds were tuned on the target camera and must be revalidated if camera or lighting changes.

Occluded or uncertain frames are skipped. A new table inventory is accepted only after it reads identically on consecutive clear frames for `--stable-seconds` (default 0.5). Flicker or occlusion restarts the streak. While a differing reading is settling, the previous suggestion is hidden; if the table reads as the accepted state again, the suggestion returns.

The difference between consecutive accepted inventories becomes observations for the unchanged rules accumulator: fewer reds is a red pot (with count), a missing colour is a colour pot, a returned colour is a respot. One accepted change may contain reds plus at most one colour pot, or respots alone. More reds than before, two missing colours or respots mixed with pots abstain for the rest of the frame.

**Approved rule change:** in shot mode a ball confirmed missing establishes a pot; pocket-transition evidence is not required. Stable identical clear readings, the monotonic red count and the change rules are the safeguards. A colour potted and respotted entirely while the cloth is occluded is still missed.

The starting table must be interpretable from the inventory: reds remaining with all six colours spotted, or (no reds) the highest remaining colours in clearance order. A mid-frame start keeps the current visit unavailable (`run_started_before_baseline`, since earlier pots were unseen) until the next committed entry. Confirming a start clears earlier pre-start observation failures; ongoing conditions such as unresolved exposure timing remain. A rejected start is logged once per distinct reading as `baseline_check`.

Capture gaps and unknown timing remain explicit failures. Submitting a score while a change is settling leaves the next run uncertain. Nothing rewrites a frozen score-entry prediction. The Flutter client polls predictions every 0.5 seconds.

`--save-inference-frames` keeps the first and last frame of each accepted change (and the start), with detected balls marked, plus their readings, in the private session folder.

## Start a dry-run test

Keep the existing pairing token and camera URL in the companion environment. Stop the prior server before installing updated code; keep session data intact. From the repository root:

```sh
companion/.venv/bin/python -m pip install ./companion
companion/.venv/bin/python -m ai_scoring.app \
  --data-directory companion/data \
  --mode dry-run --host 127.0.0.1 --port 8443 \
  --inference-enabled --inference-trigger shot \
  --calibration-file companion/data/calibration.json \
  --sample-fps 10 --max-frame-gap-seconds 1 \
  --capture-timeout-seconds 10 \
  --stable-seconds 0.5 --save-inference-frames
```

Measured capture uncertainty is still required. For the separately authorized assumed-timing experiment only, append `--capture-uncertainty-ms 2000 --max-capture-uncertainty-ms 2000`. That assumption is not evidence of synchronization or accuracy.

Recording remains independently optional. With recording and inference both enabled, only the recorder connects to the camera: it also relays an unmodified copy of the stream over loopback UDP (`udp://127.0.0.1:<port>`), and live tracking reads that relay. The target camera refused a second simultaneous stream, so this is required there. If recording fails to start, tracking connects to the camera directly; if recording stops (for example on storage limits), tracking stalls and reports a capture failure. Use `--recording-enabled` with explicit retention/storage/segment settings to keep sessions as a test dataset. Android emulator testing uses `adb reverse tcp:8443 tcp:8443` and the debug-localhost HTTP configuration.

## Manual checks

1. Start a frame with no colour waiting to be respotted; the start is accepted within about a second of a clear view.
2. Pot a red: the suggestion disappears, then shows the new total about half a second after the balls stop.
3. Pot a colour and respot it: expect a colour pot, then a respot.
4. Lean over the table without potting: the suggestion should return unchanged.
5. Enter scores manually and inspect the original comparisons and saved frames.

This test does not establish real-game accuracy.

## Validation — 2026-10-29

Live dry-run frames showed local VLMs (`qwen3-vl:4b-instruct`, `gemma3:12b`) unable to read the pale pink and brown reliably. The colour detector read saved live frames exactly (15 reds and six colours; 14 reds with the potted green absent). A live test with motion-gated reading accepted the start and a red pot correctly but missed a blue potted and respotted during continuous movement near the rail, which motivated continuous tracking. Replaying the saved frames through tracking produced the start and a red plus green pot (4 points), matching the entered break, at about 8 ms per frame. All 136 companion tests and 18 Flutter tests pass. Live accuracy remains unverified.

## Model-based ball reading — 2026-11-03

`--ball-model <file.onnx>` replaces ball finding in shot mode with an exported YOLO detector (`services/ball_model.py`); capture at the model's width (`--inference-width 1280 --inference-height 720`). The colour rules still label each box (the model's colour is the fallback when they cannot decide) and still provide the blocked-view check, on a half-size copy; the bare-cloth check, stable period, change rules and scoring rules are unchanged. Without `--ball-model` the colour rules are used as before. Install the optional runtime with `pip install './companion[model]'` (ONNX Runtime 1.31.0, NumPy 2.3.5; Core ML on Apple silicon).

The first model, `ball-table-v8n.onnx`, is YOLOv8-nano trained on the public "gezi" broadcast dataset (CC BY 4.0) and fine-tuned on 120 reviewed frames from one session. On 30 held-out frames from the end of that session it read the whole table exactly in 63% of frames (colour rules alone: 33%), found 96% of balls with no extra detections and coloured 92% correctly; the main remaining error is pink read as red. It ran at a median 49 ms per 1280×720 frame on an M5 Pro. These frames share a session with the training data, so the next unseen session is the real test. `scripts/run-session.sh` starts a session with this configuration.
