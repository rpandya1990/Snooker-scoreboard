# Record your next game and debug failed predictions

Recording and the experimental local model are optional and default off. See [Local vision scoring](local-vision-scoring.md) for inference settings.

## Set up and record

Run from the repository root on the computer beside the camera. Python 3.11+, FFmpeg and ffprobe are required; the companion supports macOS/Linux POSIX file locking.

```sh
python3 -m venv companion/.venv
companion/.venv/bin/python -m pip install ./companion
```

Load `AI_SCORING_CAMERA_URL` and `AI_SCORING_API_TOKEN` into the service's protected environment. The latter is the app-to-companion pairing token (at least 16 characters). Camera credentials stay out of app configuration, source, logs and datasets. FFmpeg necessarily receives the source URL as a process argument, so use a trusted host/account.

Recording defaults off. Choose retention, recording cap, free-space reserve and segment duration explicitly. This example chooses seven days, 10 GiB, 1 GiB and approximately 60-second segments; these are example operator settings, not defaults or measured recommendations. Adjust them for your host. Storage checks are periodic rather than an OS hard quota.

Replace the host placeholder with the companion address on your LAN:

```sh
RECORDINGS_DIR="$(pwd -P)/companion/data"
companion/.venv/bin/python -m ai_scoring.app \
  --data-directory "$RECORDINGS_DIR" --mode dry-run \
  --host "<companion-LAN-address>" \
  --recording-enabled --retention-seconds 604800 \
  --recording-total-bytes 10737418240 \
  --recording-min-free-bytes 1073741824 --segment-seconds 60
```

Configure Flutter with `AI_SCORING_MODE=dry-run`, the companion HTTP endpoint and pairing token as described in the [main README](../README.md#ai-scoring-foundation). Opening the scoreboard acquires the lease and starts recording; server startup alone does not record a match. Keep the scoreboard active and connected during play. Closing it or losing heartbeats stops capture after lease expiry. Reconnecting an expired session creates a new epoch with its gap retained; frame changes add markers without restarting video.

Session/heartbeat responses expose `recordingHealth`. Verify segment files appear during setup. Unexpected RTSP termination records collection loss. A process alive without producing bytes has no separate stall detector; process status alone does not certify footage. Actual camera compatibility has not been tested here.

## Saved files

```text
companion/data/sessions/<session-id>/
  session.jsonl
  video/segment-<epoch>-000000.mkv
```

The log links frame/run boundaries, predictions, submitted scores and corrections to video asset IDs, checksums and timing metadata. Original recording alignment is unknown: receipt time alone cannot establish camera exposure time.

## Inspect a failure directly

Stop the companion first, then inspect the session using the saved log and video:

```sh
companion/.venv/bin/python -m ai_scoring.debug_failures \
  --data-directory "$RECORDINGS_DIR" --session-id "<session-id>"
```

The default lists scoring mismatches and missing/unavailable predictions. Add `--entry-id "<entry-id>"` for one entry (including a match), or `--json` for structured output. Each report links sanitized diagnostics and safe local video candidates; missing/expired/unfinished recordings are flagged. Unknown clock alignment cannot exclude distant segments or supply exact offsets.

The score you entered is the expected value **for debugging**, not independently established truth. AI-selected/edited submissions are marked influenced, and corrections/undo remain visible. This command performs no recovery, recording, inference, session writes; it rejects an active session writer. Verified accuracy measurement remains future work.
