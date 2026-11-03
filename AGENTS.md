# AGENTS.md

Context for coding agents working in this repository.

## What this is

A Flutter snooker scoreboard (landscape tablet layout, local player storage via `shared_preferences`, leaderboards, sounds) plus an **experimental, optional AI break-scoring system**: a separate Python "companion" service watches an RTSP camera, uses a local Ollama vision model to detect pots, and offers the player a suggested break score. Manual entry is always primary and authoritative.

## Layout

| Path | Purpose |
| --- | --- |
| `lib/pages/` | Scoreboard UI. `scoreboard_page.dart` is where AI hooks into score entry (`freeze`, `commit`, `correction`, `newFrame`, `stop`, `canSuggest`). |
| `lib/ai_scoring/coordinator.dart` | `AiCoordinator`: session/frame/run IDs, ordered event outbox, 2 s sync loop (deliver → heartbeat/clock offset → poll prediction), pre-input prediction freeze. |
| `lib/ai_scoring/client.dart` | HTTP transport (HTTP only for private/loopback/`.local` hosts), atomic JSON pending-event store with cross-restart replay. |
| `companion/src/ai_scoring/app.py` | CLI entry point and all runtime flags. |
| `companion/src/ai_scoring/activity/http.py` | Four bearer-token endpoints under `/v1/sessions`. |
| `companion/src/ai_scoring/services/sessions.py` | Single camera lease (30 s), starts/stops recorder and live observer. |
| `companion/src/ai_scoring/services/scoring.py` | `ScoringService`: append-only JSONL state machine, event validation/idempotency, immutable predictions, comparisons, availability reasons. |
| `companion/src/ai_scoring/domain/scoring.py` | `SnookerAccumulator`: clean-play rules (red/colour alternation, multi-red, respots, clearance). |
| `companion/src/ai_scoring/services/live_observer.py` | Capture + inference threads; periodic mode queues model jobs, shot mode tracks every frame in the capture thread. |
| `companion/src/ai_scoring/domain/ball_detection.py` | Shot-mode colour-blob ball detector (no model); thresholds tuned to the target camera/lighting. |
| `companion/src/ai_scoring/services/ball_model.py` | Optional ONNX ball detector for shot mode (`--ball-model`); colours from the colour rules, model colour as fallback. Needs the companion `[model]` extra. |
| `scripts/run-session.sh` | Start an assist session (model tracking, recording, dataset extraction + review prep after Ctrl+C). |
| `companion/src/ai_scoring/services/inventory_adapter.py` | Shot-mode tracker: reads every frame, accepts inventories stable for `--stable-seconds`, diffs them into pot/respot observations; supports mid-frame starts. |
| `companion/src/ai_scoring/services/ollama_adapter.py` | Periodic-mode multi-frame Ollama adapter with JSON-schema output; returns observations, never totals. |
| `companion/src/ai_scoring/debug_failures.py` | Read-only CLI listing prediction-vs-submitted mismatches. |
| `companion/src/ai_scoring/services/dataset_builder.py`, `ai_scoring.dataset` | Extract pre-labelled training frames from finished recorded sessions into `companion/data/dataset/` (YOLO layout). |
| `datasets/ground-truth/` | Committed human-reviewed ball labels + frames, one folder per local session date (written by `training/import_review.py`). Public repo: frames show the playing area and people. |
| `training/` | Separate Ultralytics environment (`training/.venv`): public-data detector training, table evaluation, and `prepare_review.py` (model boxes + colour rules + score check → review queue). |
| `docs/` | PRD, design, simplification amendment, validation log, setup guides. Read `ai-break-scoring-validation.md` for current status. |

## Core invariants (do not break)

- **Mode defaults to `off`.** `off` starts nothing; `dry-run` records comparisons with no AI UI; `assist` shows an editable suggestion. AI never changes a score on its own.
- **The VLM proposes observations; the rules accumulator computes points.** Never let a model-supplied total become a prediction. In shot mode a ball counts as potted only when clear frames read it gone consistently for the stable period (see `docs/shot-triggered-inference.md`).
- **Submitted/entered scores never feed inference or rules state.** They are only stored as provisional comparison labels.
- **Predictions are immutable and frozen before input begins.** A prediction created after `inputStartedAt` must never be attached to that entry; late results cannot rewrite earlier ones.
- **When in doubt, abstain.** Any gap, stale result, pending shot, epoch change, uncertain timing, or unsupported sequence makes the prediction `unavailable` with explicit `qualityReasons`.
- **A committed break resets run points but preserves physical table state** (remaining reds, clearance progress, pending respots). Corrections/undo mark labels, never rewind the table.
- **Durability:** one writer per `session.jsonl`; records are flushed before acknowledgement; state is rebuilt by replay. Event IDs are idempotent; sequences are strictly ordered.
- **Secrets:** camera URL (`AI_SCORING_CAMERA_URL`) and token (`AI_SCORING_API_TOKEN`) live only in the companion environment. Never put them in source, docs, logs, Flutter config, or session records. Ollama endpoints must be numeric loopback.
- Local scoring must never block on the observer, network, or storage.

## Build and test

Companion (Python 3.11+, stdlib only). Reinstall after any source edit; tests import the installed package, not `src` via `PYTHONPATH`:

```sh
python3 -m venv companion/.venv
companion/.venv/bin/python -m pip install ./companion
companion/.venv/bin/python -m unittest discover -s companion/tests
```

Loopback HTTP tests need local network permission in sandboxed environments.

Flutter:

```sh
flutter test --no-pub
flutter build apk --debug --no-pub
```

Run the app against a companion with `flutter run --dart-define-from-file=<private-config.json>` (keys `AI_SCORING_MODE`, `AI_SCORING_ENDPOINT`, `AI_SCORING_TOKEN`; keep the file untracked).

## Conventions

- Match surrounding style: the Python is compact (short lines joined with `;`, minimal comments, stdlib only); comments explain safety/invariant reasoning, not mechanics.
- Companion layering: `activity/` (inbound HTTP), `services/` (orchestration), `domain/` (pure logic), `clients/` (camera, FFmpeg, Ollama), `dao/` (JSONL storage).
- New quality/failure states should be explicit reason strings recorded in the session log, not silent drops.
- Bump `PROMPT_VERSION` in `inventory_adapter.py` / `ollama_adapter.py` when that prompt or output schema changes.
- Update `docs/ai-break-scoring-validation.md` with dated, factual results when validation changes; do not claim accuracy or real-camera behavior that was not measured.

## Current status (2026-10-29)

- 136 companion tests and 18 Flutter tests pass. Shot mode tracks every frame with local colour detection (no model) and can start mid-frame; changes are uncommitted in the working tree.
- Unverified: live RTSP behavior, real-camera counting accuracy, motion recall, and the >90% exact-break accuracy launch gate.
