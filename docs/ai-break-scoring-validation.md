# AI scoring implementation status — 2026-10-06

**Independent QA result:** PASS WITH ISSUES for the implemented foundation. The complete live-camera feature is not yet accepted.

## Implemented and verified

- Independent companion Python package in this repository: clean-play rules, JSONL records, durable ordered/idempotent event delivery, safe recovery and authenticated lifecycle/prediction API.
- Flutter configuration defaults off; dry-run adds no AI UI. Optional assist uses a frozen pre-input prediction, fills an editable value and changes scores only on explicit confirmation.
- Grouped positive taps create one entry. Corrections/undo preserve comparison provenance. Session exit finalises pending entries; JSON pending files retain and retry prior-session events after restart.
- Review/export/evaluation commands distinguish submitted points from independent truth. Missing predictions count as failures for eligible reviewed breaks. Evidence sufficiency is explicitly reviewer-attested; held-out accuracy is reported separately. Synthetic samples cannot approve rollout.
- Runtime data and credentials are excluded from source control. Existing player-stat storage is retained.

## Validation evidence

| Check | Result |
| --- | --- |
| Installed companion package, `python -B -m unittest discover -s companion/tests -v` | 24 tests passed independently; no `PYTHONPATH` workaround. Includes HTTP loopback tests. |
| `flutter test --no-pub` | 13 tests passed, including original regressions, grouped deduction/undo, frozen AI fill/edit, expiry/manual fallback and lost-ack/restart recovery. |
| `flutter build apk --debug --no-pub` | Passed; generated `build/app/outputs/flutter-apk/app-debug.apk` with default-off configuration. |
| Flutter analysis | No errors after repairing an existing malformed `player.loadStats` call. Existing warnings/information remain, including missing lint include, unused code, an unnecessary null comparison and deprecated `WillPopScope`. |
| Package startup, synthetic replay and dataset commands | Verified. Off starts no observer server. Synthetic red–black–red–pink produces 15 and records manual mismatch 12. |
| Diff whitespace and credential inspection | Passed; supplied camera connection details were not added to source/docs. |

The Android build emitted existing toolchain compatibility warnings; no Gradle/Kotlin upgrade was made for this feature. No physical-device session or real camera performance was tested. No commits, push, PR publication or deployment was performed.

## Foundation acceptance work (historical; superseded below)

1. Confirm companion host/platform and protected camera configuration.
2. Validate RTSP footage and camera geometry; select/connect the visual adapter/model. No camera or external model was contacted in this implementation.
3. Implement bounded reviewable visual evidence capture and agree retention/access/storage settings.
4. Validate real app-to-companion sessions on the target device with trusted TLS, configured operating thresholds, feed gaps and recovery.
5. Independently review a predesignated held-out dataset against the >90% exact-score gate and agreed sample-size/confidence targets.

The running companion deliberately returns unavailable predictions until the visual adapter is connected. AC1–AC5 infrastructure and synthetic behavior have checks; AC3's actual background inference, AC4's real-feed behavior, AC5's visual evidence and AC6's measured accuracy remain unverified. Leave the deployed default off.

## Next-step media diagnostic

Added a default-off, read-only `python -m ai_scoring.probe` diagnostic. An explicit enabled mode can inspect the configured camera or an existing local recording; it exports only selected video metadata and sanitised health reasons. It records no footage and runs no inference.

SDE's installed-package suite passed 33 tests, including 9 new probe tests; QA independently passed those 9 tests without connecting a camera. Root generated a temporary synthetic 320x180 MPEG-4 clip at 10 fps and verified those values through the installed CLI and real ffprobe. This proves local recorded-file metadata plumbing, not real RTSP availability or camera scoring.

[Recording dataset requirements](ai-scoring-datasets-requirements.md) and the [design extension](ai-scoring-datasets-design.md) describe proposed future session capture, timestamped provenance and offline improvement. Live capture, visual inference, bounded evidence storage and recorded-session replay are still pending.

## Approved recording/dataset extension implemented

This section supersedes the earlier pending recording/evidence/replay statements. Default-off, locally configured FFmpeg recording, bounded closed-asset retention, isolated dataset import, persistent tuning/held-out cohorts, versioned alignment, blind independent reviews, local-adapter offline replay and reviewed replay evaluation are implemented. No production visual adapter or automatic training/deployment is configured.

**Final installed-package run:** `/private/tmp/snooker-companion-venv/bin/python -B -m unittest discover -s companion/tests` passed **71 tests**. Independent QA passed the preceding complete 69-test suite and independently reran 19 affected recording/lifecycle tests after the two final stream-termination cases were added. No `PYTHONPATH` workaround was used.

Tests cover private storage/symlink rejection, immutable checksummed import, live-writer refusal, transitive cohort isolation, decoder deadlines, strict pre-input footage cutoffs, uncertain boundaries/delayed observations, source gaps/missing tails, answer-free adapter inputs, separate reviewed labels and missing-prediction failures in replay metrics.

Root's real FFmpeg smoke used a generated local H.264 clip: six playable MKV segments and a manual score event were saved, then the periodic lease watchdog stopped recording. A real decoder produced six correctly sized RGB frames through a 0.5-second cutoff. Importing that recording, assigning tuning, blind listing, unconfigured replay and evaluation preserved the source hash and reported unavailable prediction/no accuracy claim. No camera was contacted.

The Android debug APK rebuilt successfully after adding the main-manifest network permission. iOS purpose text and macOS client entitlements passed plist validation; previous 13 Flutter tests remain applicable because Dart integration did not change in this extension. Physical Apple/Android device connectivity and certificate/permission behavior remain untested.

**QA result:** PASS WITH ISSUES for the recording/dataset extension. Capture exposure alignment remains unknown until measured/reviewed. Storage checks are periodic rather than a hard OS quota; a live process producing no bytes has no separate stall detector, so operators must verify assets are appearing. Unexpected RTSP termination is reported as collection loss. Actual camera/model feasibility and the independently reviewed >90% launch gate remain unproven.

See [Record your next game](record-your-next-game.md) for protected configuration and collection/import/review/replay commands. No actual recordings, model uploads, automatic training, deployment, commits or GitHub publication were performed.


## Local vision integration — 2026-10-06

The experimental Ollama adapter now supports offline replay and bounded live observation. Inference defaults off, targets numeric loopback only and sends image data to the local model. Model digest, prompt, sampling, calibration and runtime provenance are recorded. Missing calibration, uncertain exposure timing, incomplete evidence, duplicates, queue gaps and stale jobs suppress scoring output. Late jobs cannot change a new run or improve an already frozen prediction. Submitted/reviewed scores are excluded from inference inputs.

**Independent QA:** PASS WITH ISSUES; all **105 installed-package companion tests passed**. Tests include local endpoint/model validation, structured visual evidence, calibration gates, deadline/queue behavior, run isolation and failure cleanup. No Dart behavior changed in this stage; the previous Flutter checks remain applicable.

Local trials used only the supplied reference screenshot, not a live camera or actual breaks. Gemma3:12b took approximately 18.9 seconds for the full adapter request; locally downloaded Qwen3-VL:4b-instruct took approximately 12.7 seconds. Both abstained and exceeded the default five-second job freshness limit. This establishes local integration, not usable live throughput or scoring accuracy. Model weights were downloaded; footage stayed local.

The current shell has neither the protected camera URL nor companion pairing token configured, so no real RTSP validation was performed. Remaining acceptance requires camera geometry/calibration, measured exposure alignment, representative gameplay and sustained throughput, physical-device TLS/connectivity, and independent held-out evaluation against the >90% exact-break target. Leave the deployed default off and begin with recorded replay or explicitly configured dry-run. No automatic training, deployment, commits, push or GitHub publication occurred.

See [Local vision scoring](local-vision-scoring.md) for setup, model trials and limitations.
