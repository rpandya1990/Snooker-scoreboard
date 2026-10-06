# Record your next game and build a test dataset

Session recording and offline dataset tools are implemented. An experimental [local Ollama adapter](local-vision-scoring.md) is available and defaults off. Early recordings can collect video and user-entered scores; original AI predictions remain explicitly unavailable whenever inference is disabled or quality gates fail. Later offline predictions are stored separately from those original results.

## Set up and record

Run from the repository root on the computer beside the camera. Python 3.11+, FFmpeg and ffprobe are required; the companion supports macOS/Linux POSIX file locking.

```sh
python3 -m venv companion/.venv
companion/.venv/bin/python -m pip install ./companion
```

Load `AI_SCORING_CAMERA_URL` and `AI_SCORING_API_TOKEN` into the service's protected environment. The latter is the app-to-companion pairing token (at least 16 characters). Camera credentials stay out of app configuration, source, logs and datasets. FFmpeg necessarily receives the source URL as a process argument, so use a trusted host/account.

Check stream metadata first; this saves no footage:

```sh
companion/.venv/bin/python -m ai_scoring.probe --mode dry-run
```

Recording defaults off. Choose retention, recording cap, free-space reserve and segment duration explicitly. This example chooses seven days, 10 GiB, 1 GiB and approximately 60-second segments; these are example operator settings, not defaults or measured recommendations. Adjust them for your host. Storage checks are periodic rather than an OS hard quota.

Replace the host/certificate placeholders and use a certificate trusted by the app device:

```sh
RECORDINGS_DIR="$(pwd -P)/companion/data"
companion/.venv/bin/python -m ai_scoring.app \
  --data-directory "$RECORDINGS_DIR" --mode dry-run \
  --host "<companion-LAN-address>" \
  --cert "/absolute/path/server.crt" --key "/absolute/path/server.key" \
  --recording-enabled --retention-seconds 604800 \
  --recording-total-bytes 10737418240 \
  --recording-min-free-bytes 1073741824 --segment-seconds 60
```

Configure Flutter with `AI_SCORING_MODE=dry-run`, the companion HTTPS endpoint, matching camera alias and pairing token as described in the [main README](../README.md#ai-scoring-foundation). Opening the scoreboard acquires the lease and starts recording; server startup alone does not record a match. Keep the scoreboard active and connected during play. Closing it or losing heartbeats stops capture after lease expiry. Reconnecting an expired session creates a new epoch with its gap retained; frame changes add markers without restarting video.

Session/heartbeat responses expose `recordingHealth`. Verify segment files appear during setup. Unexpected RTSP termination records collection loss. A process alive without producing bytes has no separate stall detector; process status alone does not certify footage. Offline coverage checks reject missing intervals. Actual camera compatibility has not been tested here.

## Saved files

```text
companion/data/
  sessions/<session-id>/
    session.jsonl
    video/segment-<epoch>-000000.mkv
  datasets/
    registry.jsonl
    <dataset-id>/
      dataset.json
      session.jsonl
      video/
      alignment.jsonl
      reviews.jsonl
      replays/<replay-run-id>/replay.json
```

The log retains video asset IDs/checksums, media offsets, clock anchors/uncertainty, frame/run markers, immutable pre-input predictions, submissions, applied deltas, input source and correction/undo references. Audio is omitted. Original capture alignment is marked unknown: packet receipt time does not establish exact camera exposure time.

## Import and assign cohorts

Finish the scoring session and stop the companion to release its writer before import. Live-owned logs are refused. Use a canonical private dataset directory; symlink roots/assets are rejected. `companion/data` is excluded from Git.

```sh
DATASETS_DIR="$(pwd -P)/companion/data/datasets"
companion/.venv/bin/python -m ai_scoring.recorded_dataset \
  --root "$DATASETS_DIR" import "$RECORDINGS_DIR/sessions/<session-id>"
```

Use the returned dataset ID. Assign before review/replay or inspecting evaluation outcomes:

```sh
companion/.venv/bin/python -m ai_scoring.recorded_dataset \
  --root "$DATASETS_DIR" cohort "<dataset-id>" tuning
```

Use `held-out` for final evaluation recordings. Related sessions/asset identities cannot switch cohorts through another import. Archive copies are private and independent of recording retention; manage their retention deliberately for future tests.

## Align and review

List entry boundaries/video references without score answers:

```sh
companion/.venv/bin/python -m ai_scoring.recorded_dataset \
  --root "$DATASETS_DIR" blind-review "<dataset-id>"
```

Watch the footage to establish actual points, supported play and boundary validity. Submitted scores remain provisional; accepting AI alone does not establish correctness.

An alignment JSON file contains `version`, `reviewer` and measured mappings:

- `assets`: `assetId`, `captureStartUtc`, `utcUncertaintyMs`.
- `frames`: `frameId`, `frameStartedAt`, `utcUncertaintyMs`.
- `entries`: `entryId`, `inputStartedAt`, optional `committedAt`, `utcUncertaintyMs`.

Use timezone-bearing timestamps and justified nonnegative numeric uncertainty. Leave alignment unknown until source timestamps or a synchronisation reference establish it; unresolved alignment produces unavailable replay results. Do not set uncertainty to zero merely to enable predictions.

```sh
companion/.venv/bin/python -m ai_scoring.recorded_dataset \
  --root "$DATASETS_DIR" align "<dataset-id>" /absolute/path/alignment.json
```

A review JSON file contains `entryId`, `reviewer`, `independent: true`, `evidenceSufficient: true`, `eligible: true` and independently established integer `actualPoints`. Corrected/undone entries need `resolvesRevision: true` when review has resolved their history. Unsupported/ambiguous examples use `eligible: false` and `exclusionReason`. Cohort comes from the registry, not the review file.

```sh
companion/.venv/bin/python -m ai_scoring.recorded_dataset \
  --root "$DATASETS_DIR" review "<dataset-id>" /absolute/path/review.json
```

Reviews/mappings append records without changing original video, predictions or submissions.

## Replay and improve

A trusted local adapter factory supplies versioned model/prompt/configuration/sampling/calibration/runtime metadata. Its [contract](../companion/src/ai_scoring/domain/visual_adapter.py) receives timestamped RGB frames with dimensions and boundary context, and returns structured observations. It receives no score answers or original AI totals. Only footage within the conservative pre-input cutoff is supplied.

```sh
companion/.venv/bin/python -m ai_scoring.recorded_dataset \
  --root "$DATASETS_DIR" replay "<dataset-id>" \
  --adapter "your_local_adapter:create" --settings /absolute/path/model-settings.json
```

Omitting the adapter produces unavailable results. Use the returned run ID to evaluate against independent reviews:

```sh
companion/.venv/bin/python -m ai_scoring.recorded_dataset \
  --root "$DATASETS_DIR" evaluate "<dataset-id>" "<replay-run-id>"
```

Improve versioned prompts/model settings using tuning recordings, then evaluate untouched held-out recordings. Missing predictions remain failures for eligible reviewed breaks. Offline results cannot replace live history or approve rollout. Collection/replay do not update model weights or deploy changes; automatic training is outside scope. No >90% camera accuracy has been established.

Network declarations were added for companion access. Current Android builds target SDK 36; future SDK 37 adoption requires the additional runtime flow in [Android's guidance](https://developer.android.com/privacy-and-security/local-network-permission). Apple builds include the [local-network purpose description](https://developer.apple.com/documentation/bundleresources/information-property-list/nslocalnetworkusagedescription) and macOS [network-client entitlement](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.network.client). Actual device permission and TLS behavior remain untested.
