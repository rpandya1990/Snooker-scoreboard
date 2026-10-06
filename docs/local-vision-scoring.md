# Local vision scoring — experimental integration

**Status:** Local Ollama adapter and asynchronous live observation are implemented. Production scoring accuracy and throughput are not established. Inference defaults off; use dry-run and recorded datasets first.

The approved `VisualAdapter.observe(frame, BoundaryContext)` contract is reused. Ollama sees ordered images and observation context; it never receives submitted scores, reviewed labels or original AI totals. It returns candidate observations, and the existing rules accumulator calculates points.

## Runtime and model checks

This Mac was verified as an Apple M5 Pro with 48 GiB memory and Ollama 0.34.0. Existing local vision models were `gemma3:12b` and `gemma4:e4b`. A local `qwen3-vl:4b-instruct` model was additionally downloaded for comparison; its official artifact is approximately [3.3 GB](https://ollama.com/library/qwen3-vl:4b-instruct). The download transferred model weights, not footage. No existing model or global Ollama configuration was replaced.

Reference-image checks used the screenshot supplied for this feature, on localhost only:

| Check | Result |
| --- | --- |
| Gemma 3, simple visibility/count schema | 6.58 seconds; 15 reds and six colours, with red-count uncertainty. |
| Gemma 4, same simple schema | 4.36 seconds; six reds without reported uncertainty, inconsistent with the reference. |
| Gemma 3, full three-frame adapter | 18.90 seconds; baseline declined, no events. |
| Qwen 3-VL 4B, full three-frame adapter | 12.68 seconds; baseline declined, no events. |

The full-adapter checks repeated a static reference image as explicitly synthetic frame inputs. They establish local API/schema/abstention behavior, not temporal event detection or break accuracy. Results are individual observations, not a performance benchmark distribution. The full calls exceeded the default five-second live freshness bound; stale results are deliberately unavailable. Neither model is recommended for broad assist rollout from these checks.

Ollama's [vision API](https://docs.ollama.com/capabilities/vision) accepts images, and its [structured-output API](https://docs.ollama.com/capabilities/structured-outputs) accepts a JSON schema. The adapter uses these local capabilities, temperature zero, a fixed seed and bounded context/output settings. Those settings do not guarantee correct or identical predictions.

## Locality and observation rules

- Only numeric loopback HTTP endpoints with an explicit port are accepted, such as `http://127.0.0.1:11434`. Proxies, redirects, cloud models and external endpoints are rejected. The model must already be installed and advertise vision support; runtime code does not pull models.
- The first two frames warm the window without a model call. Baseline confirmation requires at least three distinct chronological, settled witnesses, all 15 initial reds and six colours, adequate confidence, visibility and pocket calibration. It does not initialise an arbitrary mid-clearance table.
- Candidate pots/respots require ordered evidence and referenced input frames. Missing balls alone do not establish a pot. Unknown refs/types/counts, duplicate or overlapping events, uncertainty and unsupported conditions abstain.
- Event timestamps come from referenced input frames, not model-generated clocks. The adapter preserves table baseline across run boundaries and resets on physical frame changes/discontinuity.
- Fixed versions, model digest, prompt, calibration, actual sampling and latency remain in provenance. Original frozen score-entry predictions are never replaced by later results.

## Offline replay first

Use [recorded dataset setup](record-your-next-game.md) to import footage, assign cohorts, establish justified clock mappings and independently review labels. Configure a trusted local adapter settings JSON. For diagnostics, this minimal example intentionally lacks pocket calibration:

```json
{
  "model": "qwen3-vl:4b-instruct",
  "endpoint": "http://127.0.0.1:11434",
  "windowFrames": 3,
  "maxFrameGapSeconds": 2.0,
  "minConfidence": 0.95,
  "seed": 0,
  "timeoutSeconds": 60,
  "maxImageWidth": 1280,
  "numPredict": 2048,
  "numCtx": 16384
}
```

For scoring, add `calibration` containing a nonempty `version`, six `pockets` as normalized `[x,y]` coordinates and positive `pocketRadius` no greater than 0.25. Coordinates must match the image after any source ROI crop. Measure/check this on the actual feed; no calibration from the reference screenshot was installed for production. Without it, even empty-event and zero-point results remain unavailable.

```sh
companion/.venv/bin/python -m ai_scoring.recorded_dataset \
  --root "/absolute/private/datasets" replay "<dataset-id>" \
  --adapter ai_scoring.services.ollama_adapter:create \
  --settings /absolute/private/vision-settings.json \
  --sample-fps 1
```

The optional replay sampling rate selects original presentation timestamps and is recorded in the run. Sparse sampling can miss shots; coverage and watermark checks remain enforced. Decoder stall time excludes time the generator is paused while the model processes a frame, so healthy backpressure is not mistaken for a stalled decoder. Individual decoder reads and model calls remain bounded.

Compare versions using the existing independent-review evaluation command. Keep tuning and held-out recordings separated. Do not count these reference/synthetic results toward the >90% gate.

## Live dry-run

Add these options to the companion startup command from the recording guide:

```sh
--inference-enabled --model qwen3-vl:4b-instruct \
--ollama-endpoint http://127.0.0.1:11434 \
--sample-fps 1 --inference-width 768 --inference-height 432 \
--window-frames 3 --max-frame-gap-seconds 2 \
--job-freshness-seconds 5 --inference-queue-size 2 \
--prediction-ttl-seconds 3 --model-timeout-seconds 30 \
--min-confidence 0.95 \
--calibration-file /absolute/private/calibration.json
```

These are initial experimental settings, not demonstrated real-time settings. They will suppress predictions when the benchmarked model falls behind. Recording and inference are independent toggles; full video collection can continue while inference reports unavailable.

Capture exposure mapping is unknown by default. A justified positive `--capture-uncertainty-ms` bound is required for eligible live predictions; `--max-capture-uncertainty-ms` defaults to 500. Do not guess a bound merely to enable scores. Receive time alone does not establish exposure time. Unknown mapping supports diagnostics and dataset collection while scoring remains unavailable.

The observer uses sampled original PTS and a bounded asynchronous queue. Queue overflow, old jobs, gaps, stale timestamps and excessive uncertainty are explicit failures. Work tagged to an earlier frame/run/epoch cannot mutate replacement state or retroactively improve a score-entry comparison. Model work stays outside HTTP score handlers. Empty-frame watermarks do not falsely mark normal input as new scoring activity.

Session leases, stop and shutdown close capture. In-flight model bodies are cancelled where possible; header waits remain bounded by the configured timeout and stopped workers reject late effects. Operators can inspect inference health in session/heartbeat metadata.

## Validation and next evidence

The installed companion suite passes 105 tests, including locality, strict schema/calibration, window warmup, duplicate suppression, run-generation checks, failures/cleanup, score-answer isolation, slow model consumers and original-PTS sampling. Existing Flutter tests remain applicable; no Dart behavior changed in this integration.

Actual RTSP, camera calibration, exposure alignment, sustained model throughput, pots/respots and held-out exact-break accuracy remain untested. Collect a real play recording next, measure the model's missed/false events and latency, and tune on reviewed training examples. Keep assist restricted until held-out results satisfy the approved gate. No automatic training, model deployment, commit or publication was performed.
