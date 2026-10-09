# AI scoring companion foundation

This independent Python package provides clean-play rules, durable per-session JSONL, authenticated lifecycle/prediction APIs, optional session recording, a failure-debugging script and an experimental local Ollama observation adapter. See [Local vision scoring](../docs/local-vision-scoring.md) for model checks, configuration and limitations. Inference defaults off and returns unavailable when calibration, time, coverage or model quality fails; real-camera accuracy is not established. It never changes scoreboard scores.

See [Record your next game](../docs/record-your-next-game.md) for recording settings, private storage and debugging commands. Recording defaults disabled and requires explicit retention/storage/free-space/segment settings.

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

For a local API, set `AI_SCORING_API_TOKEN` through your protected environment (minimum 16 characters), then:

```sh
companion/.venv/bin/python -m ai_scoring.app --data-directory /tmp/snooker-ai-data --mode dry-run
```

For LAN access specify a LAN bind address. HTTP requires no certificate; optional HTTPS uses both `--cert` and `--key` and a certificate trusted by the client. Plain HTTP exposes the pairing token and scoring traffic to the network; use it only on your trusted LAN. Keep token/camera credentials out of source, examples, logs, and datasets. The camera URL belongs in protected service-side configuration only; Flutter sends no camera configuration.

## API and records

All endpoints require `Authorization: Bearer <token>`. POST bodies are JSON objects (maximum 64 KiB). Endpoints match the approved design:

- `POST /v1/sessions`: `{sessionId, mode}`; returns metadata, `serverTimestamp`, and `leaseSeconds`.
- `POST /v1/sessions/{id}/heartbeat`: renews the 30-second lease and supplies service time.
- `POST /v1/sessions/{id}/events`: one ordered event with `eventId`, `sequence`, `type`; sequence starts at 1.
- `GET /v1/sessions/{id}/prediction`: an available immutable prediction or explicit unavailability.

Event types are `frame_started`, `frame_ended`, `break_committed`, `correction`, `undo`, `session_stopped`. Break fields follow the design (`frameId`, `runId`, `nextRunId`, `entryId`, `attemptId`, timestamps, frozen `predictionId`, points, delta, source). Manual scores are provisional labels; AI-accepted/edited entries are AI-influenced. Correction and undo records never rewind the table. Every record is linked by stable IDs; identical event retries return the original acknowledgement, conflicting IDs fail. Reopening a stopped session returns metadata without reacquiring the camera so a lost stop acknowledgement can be retried.

One writer owns `<data-directory>/sessions/<session-id>/session.jsonl`. A newline-terminated record is flushed/fsynced before acknowledgement. Recovery truncates only an incomplete tail; malformed complete records stop collection. Write failures poison the writer until reopen/recovery. Restart, lease expiry, gaps, out-of-order observations, and uncertain delayed boundaries suppress suggestions; replaying JSON does not recover unseen camera activity. Session ownership controls optional recording and local inference capture start/stop.

The internal `ScoringService.confirm_baseline`, `observe(PotObservation)`, `discontinuity`, and `publish_prediction` are internal visual adapter seams, not public HTTP endpoints. Physical rules state persists across submission-delimited run resets. An unresolved sequence/gap stays unavailable until a fresh frame/baseline. Rules cover multiple reds, alternating colours/respots, the last-red colour and ascending clearance. After yellow and green are cleared, brown is next, including across score-entry resets. Observation attached midway through clearance remains unsupported. Fouls and automatic visit detection remain excluded.

## Debug scoring failures without a UI

After stopping the companion (an active writer is rejected), list mismatches and unavailable/missing original predictions directly from its session log:

```sh
companion/.venv/bin/python -m ai_scoring.debug_failures --data-directory /absolute/path/recordings --session-id SESSION_ID
companion/.venv/bin/python -m ai_scoring.debug_failures --data-directory /absolute/path/recordings --session-id SESSION_ID --entry-id ENTRY_ID
companion/.venv/bin/python -m ai_scoring.debug_failures --data-directory /absolute/path/recordings --session-id SESSION_ID --json
```

The selected-entry command also shows matching entries. Submitted points are the **expected score for debugging**, a provisional label; AI-selected/edited entries are explicitly marked influenced. Reports include prediction errors/reasons, corrections/undo, run/input/commit timing, relevant sanitized diagnostics and local recording references. Unknown alignment includes all candidate segments—even apparently distant ones—with no exact media offsets. Known bounded timing supplies estimated candidate offsets. Missing, expired, unsafe and unfinished assets remain explicit.

This utility reads a shared-lock snapshot. It creates no directories, repairs no partial log, modifies no session records, and starts no camera/model/network operation. Incomplete logs and symlink/traversal paths are rejected without recovery. It compares against submitted scores for troubleshooting; verified accuracy remains future validation work.
