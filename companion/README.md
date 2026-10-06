# AI scoring companion foundation

This independent Python package provides clean-play rules, durable per-session JSONL, authenticated lifecycle/prediction APIs, optional session recording, dataset tools and an experimental local Ollama observation adapter. See [Local vision scoring](../docs/local-vision-scoring.md) for model checks, configuration and limitations. Inference defaults off and returns unavailable when calibration, time, coverage or model quality fails; real-camera accuracy is not established. It never changes scoreboard scores.

See [Record your next game](../docs/record-your-next-game.md) for recording settings, private storage, import/cohorts, alignment, blind review and model-version replay commands. Recording defaults disabled and requires explicit retention/storage/free-space/segment settings.

Runtime is Python 3.11+ with the standard library on macOS/Linux (file ownership uses POSIX `flock`). Build tooling uses setuptools. From the repository root:

```sh
python3 -m venv companion/.venv
companion/.venv/bin/python -m pip install ./companion
companion/.venv/bin/python -m unittest discover -s companion/tests
```

Tests use temporary directories and a loopback HTTP server. Reinstall the package after source edits; src imports require an installed package, with no `PYTHONPATH` changes. On a restricted environment, loopback tests require network permission. Off is the default and starts no server or processing:

```sh
companion/.venv/bin/python -m ai_scoring.app --data-directory /tmp/snooker-ai-data
```

For a development-only API, set `AI_SCORING_API_TOKEN` through your protected environment (minimum 16 characters), then:

```sh
companion/.venv/bin/python -m ai_scoring.app --data-directory /tmp/snooker-ai-data --mode dry-run --test-http-loopback
```

For LAN access omit `--test-http-loopback`, specify a LAN bind address, and provide `--cert` / `--key` for a certificate trusted by the client. No TLS verification bypass exists in the app. Keep token/camera credentials out of source, examples, logs, and datasets. The camera URL belongs in protected service-side configuration only; Flutter sends a camera alias.

## API and records

All endpoints require `Authorization: Bearer <token>`. POST bodies are JSON objects (maximum 64 KiB). Endpoints match the approved design:

- `POST /v1/sessions`: `{sessionId, mode, cameraAlias}`; returns metadata, `serverTimestamp`, and `leaseSeconds`.
- `POST /v1/sessions/{id}/heartbeat`: renews the 30-second lease and supplies service time.
- `POST /v1/sessions/{id}/events`: one ordered event with `eventId`, `sequence`, `type`; sequence starts at 1.
- `GET /v1/sessions/{id}/prediction`: an available immutable prediction or explicit unavailability.

Event types are `frame_started`, `frame_ended`, `break_committed`, `correction`, `undo`, `session_stopped`. Break fields follow the design (`frameId`, `runId`, `nextRunId`, `entryId`, `attemptId`, timestamps, frozen `predictionId`, points, delta, source). Manual scores are provisional labels; AI-accepted/edited entries are AI-influenced. Correction and undo records never rewind the table. Every record is linked by stable IDs; identical event retries return the original acknowledgement, conflicting IDs fail. Reopening a stopped session returns metadata without reacquiring the camera so a lost stop acknowledgement can be retried.

One writer owns `<data-directory>/sessions/<session-id>/session.jsonl`. A newline-terminated record is flushed/fsynced before acknowledgement. Recovery truncates only an incomplete tail; malformed complete records stop collection. Write failures poison the writer until reopen/recovery. Restart, lease expiry, gaps, out-of-order observations, and uncertain delayed boundaries suppress suggestions; replaying JSON does not recover unseen camera activity. Session ownership controls optional recording and local inference capture start/stop.

The internal `ScoringService.confirm_baseline`, `observe(PotObservation)`, `discontinuity`, and `publish_prediction` are internal visual adapter seams, not public HTTP endpoints. Physical rules state persists across submission-delimited run resets. An unresolved sequence/gap stays unavailable until a fresh frame/baseline. Rules cover multiple reds, alternating colours/respots, the last-red colour and ascending clearance. Fouls and automatic visit detection remain excluded.

## Synthetic replay and review

```sh
companion/.venv/bin/python -m ai_scoring.replay --data-directory /tmp/snooker-ai-data
```

This prints a newly generated session ID/path with red–black–red–pink = 15, and a manual mismatch of 12. Use the printed session ID below. Stop its service writer before dataset review/export (single writer ownership).

```sh
companion/.venv/bin/python -m ai_scoring.dataset --data-directory /tmp/snooker-ai-data --session-id SESSION_ID export
companion/.venv/bin/python -m ai_scoring.dataset --data-directory /tmp/snooker-ai-data --session-id SESSION_ID review --entry-id entry --reviewer fixture-reviewer --actual-points 15
companion/.venv/bin/python -m ai_scoring.dataset --data-directory /tmp/snooker-ai-data --session-id SESSION_ID evaluate
```

Without `--evidence-reviewed`, a review is excluded from accuracy as insufficient evidence. Add `--evidence-reference` to link inspected evidence, and `--held-out` only for a cohort designated before outcomes are reviewed. Synthetic replay is exploratory, never camera-evidence attestation. Review commands assert the human independently inspected footage/evidence; software cannot certify reviewer independence. Exclude unsupported boundaries/fouls with `--exclusion-reason`; reviewed corrected entries require `--resolves-revision`. Evaluate separates exploratory exact accuracy from held-out exact accuracy and includes missing predictions as failures, reports exact accuracy, coverage, error sizes, Wilson uncertainty, exclusions and boundary counts. It never labels AI acceptance as correct automatically or approves rollout from a small synthetic dataset. The separate recorded-dataset tools implement bounded recording, persistent cohort assignments and reviewed replay metrics. The experimental local Ollama adapter is available; real-camera compatibility, production model readiness, operational recording settings, exposure alignment and sample-size gates remain unverified.

## Read-only camera metadata diagnostic

`ffprobe` from FFmpeg is an optional prerequisite already available on the development host; it is not a Python dependency and this package does not install it. This diagnostic only probes stream metadata. It does not decode/record a full session, write footage, run a model, or assess pot visibility/accuracy. An `available` result means a video stream was identified during this one probe; `elapsed_ms` is total probe duration, not end-to-end camera latency or continuous-feed health.

Default mode `off` performs no subprocess or camera access:

```sh
companion/.venv/bin/python -m ai_scoring.probe
```

For an explicitly requested camera check, first provide the service-side URL through a protected `AI_SCORING_CAMERA_URL` environment variable, then run:

```sh
companion/.venv/bin/python -m ai_scoring.probe --mode dry-run --timeout-seconds 10
```

There is deliberately no camera-URL command-line flag. The URL is passed intact as one argument to `ffprobe`, including reserved characters in credentials; it is never printed or persisted by the companion. The external process still needs the source argument, so use a trusted companion host. Raw stderr, command details, stream tags and arbitrary metadata are not returned; failures use generic reasons such as `probe_timeout`, `ffprobe_missing`, `no_video_stream` and `invalid_probe_metadata`.

An existing local recording can be checked without camera/network access or changing its contents:

```sh
companion/.venv/bin/python -m ai_scoring.probe --mode dry-run --recorded-file /path/to/existing-session.mp4
```

Probe tests inject a fake subprocess and cover reserved userinfo, sanitized errors/timeouts, malformed metadata, absent video, unknown codec metadata and unchanged recorded files. No real camera call was performed during implementation. The approved recording/dataset extension is implemented; actual visual inference and automatic training remain outside the currently configured runtime.
