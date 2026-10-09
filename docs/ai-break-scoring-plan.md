# Implementation plan: AI-assisted break scoring

> Historical document: the approved [simplification amendment](ai-scoring-simplification-amendment.md) supersedes transport, camera-alias and shipped dataset/evaluation tooling described here.
**Basis:** [Approved PRD](ai-break-scoring-prd.md) and [approved design](ai-break-scoring-design.md). Architecture approved on 2026-10-05. Root owns planning and integration; SDE owns implementation; QA independently validates completed behavior.

**Progress:** Companion rules/storage/API, Flutter dry-run/optional assist, recording/dataset tools and experimental local Ollama live/replay inference are implemented. Latest companion validation passed 105 tests; Flutter passed 13 tests and an Android debug build. Actual camera feasibility, model throughput, device connectivity and held-out rollout evaluation remain unverified; see [validation status](ai-break-scoring-validation.md) and [local setup](local-vision-scoring.md).

## Repository layout and approach

Keep one repository. Add `companion/` as an independently runnable Python package with its own dependencies and tests. Add `lib/ai_scoring/` for Flutter configuration, event delivery and prediction state. Existing `lib/pages/scoreboard_page.dart` and `lib/pages/player.dart` retain authoritative local scoring. Save runtime JSON/evidence in a configurable directory outside tracked source; ignore generated data and credentials.

Deliver dry-run before optional AI UI. Keep the default mode off throughout development. Use JSONL for per-session records and a small JSON file for pending client events; no database, broker, player recognition or automatic score updates. Do not treat synthetic visual observations as proof of real-camera performance.

## Decisions and prerequisites

Before collecting real footage, confirm the companion host, protected camera settings, data directory, evidence retention/storage cap and access policy. Do not embed credentials in code, examples or tests. External model uploads require a separate explicit choice; default to no evidence leaving the LAN.

Choose the initial visual adapter/model from a small recorded-footage feasibility assessment. Set configurable freshness, settle-time, replay-window, clock uncertainty and session lease thresholds before live integration. Predeclare held-out evaluation sample size/confidence targets before rollout evaluation.

Inspect installed Flutter/Dart/Python tooling before selecting compatible dependencies. Establish a baseline of existing tests and distinguish pre-existing failures from regressions. In particular, check the current Dart SDK constraint against the installed toolchain instead of silently upgrading the app.

## Ordered implementation tasks

| Task / owner | Objective and likely files | Dependencies / concurrency | Verification and completion |
| --- | --- | --- | --- |
| 1 — SDE: camera feasibility | Add minimal capture/replay tooling under `companion/`; validate table/pocket calibration, usable near/far detail and continuity. Record only after collection settings are settled. | First; can run independently of task 2 after contracts are agreed. Root reviews findings and adapter recommendation. | Demonstrate representative red/colour pots and respots on actual footage; identify unobservable cases. Report resolution/gaps and local resource requirements. A failed view assessment leads to camera adjustment, not an accuracy claim. |
| 2 — SDE: contracts, rules and JSON records | Define typed session/frame/run/entry/prediction records, visual observations, rules accumulator and single-writer JSONL persistence in `companion/src/ai_scoring/`; add fixtures/tests. | Independent of live camera; agrees event contracts before Flutter work. One SDE owns these files. | Prove multiple reds, red–black–red–pink = 15, respots counted once, last-red transition, new-visit ball-on reset and final clearance. Verify immutable predictions, null predictions, duplicate delivery, trailing partial-write recovery and correction revisions. |
| 3 — SDE: observer service | Add inbound lifecycle/prediction API, capture/adapter clients, continuity monitor, lease ownership, bounded evidence and sanitised configuration. Wire task 1 adapter to task 2 rules/storage. | Depends on tasks 1–2 for real inference. Synthetic observations may validate contracts earlier, but cannot stand in for a camera-ready service. | Run a companion session, retrieve a prediction and inspect its JSON/evidence. Feed loss, restart, camera movement, model failure and stale state suppress suggestions. Repeated commits reset once; missing sequences/uncertain boundary placement fail visibly. No submitted score enters inference. |
| 4 — SDE: Flutter dry-run integration | Add `lib/ai_scoring/` config/client/coordinator/pending-event JSON; integrate frame/entry/exit callbacks and stable IDs into scoreboard/player history. Keep AI UI hidden. | Begins after task 2 contracts; may run in parallel with task 3 using a fake service. Assign separate Flutter owner; coordinate any shared docs/dependency edits. | Widget/fake-service tests prove off does no AI work; dry-run has unchanged UI; freeze occurs before input/first +1; grouped taps commit once; cancel does not reset; corrections/undo revise labels; offline delivery never blocks local scores. Demonstrate real app-to-companion session after task 3. |
| 5 — SDE: dry-run evaluation | Add JSON export/review/evaluation tools under `companion/`; link predictions, entries, revisions and evidence. Document local collection and review commands. | Depends on tasks 2–4 for complete collected records; tooling can start from fixtures after task 2. | Show agreement, manual mismatch, AI-selection provenance, no prediction and undo fixtures. Independently reviewed labels determine correctness; AI acceptance alone never does. Missing predictions count as failures for eligible breaks. Export reports exclusions, boundary violations, coverage and collection losses. |
| 6 — SDE: optional assist UI | Add subtle AI icon/secondary action to additive input; preserve editable manual input and existing confirmation. Record manual, AI-selected and AI-edited sources. | After dry-run integration/evaluation are verified. Implement assist behind configuration; leave default off. Broader enablement waits for the evaluation gate. Same Flutter owner as task 4. | Confirm explicit selection and submission add once; total-score editing gets no break suggestion. Late responses cannot change a frozen suggestion; stale/uncertain suggestions disappear. Tablet/phone checks preserve manual entry and undo. |
| 7 — QA: independent acceptance validation | Validate the integrated feature against AC1–AC6; review JSON datasets, tests and observed camera behavior. Root routes implementation defects to SDE for repair and QA rechecks affected behavior. | Final validation after implemented tasks; no production-code edits by QA. | Produce an acceptance report separating code correctness, camera feasibility and measured accuracy. Verify real dry-run with manual entries, disconnect/retry, frame transitions, corrections and session cleanup. Report unresolved limits; do not claim >90% until held-out evidence establishes it. |

No two agents modify the same files concurrently. Root integrates service/Flutter work and reviews any proposed contract change. Re-engage Architect only for a concrete change to approved component boundaries, contracts or consistency guarantees; routine fixes stay with SDE.

## Demonstrations and checks

Each task supplies runnable instructions for the actual tools it introduces. Establish package entry points during task 2; do not document nonexistent commands as working.

The dry-run demo must start the companion with protected local configuration, start a frame in the app, play/enter a known clean break, and show the frozen prediction, committed manual points and linked evidence in that session's JSONL. Repeat with a mismatch and an unavailable prediction. Cancel an input and undo a committed entry to demonstrate correct boundaries and label validity.

The assist demo additionally selects an AI suggestion, edits it, confirms it, and shows provenance in JSON. QA verifies platform builds/tests relevant to the configured devices and companion tests relevant to persistence, rules, continuity and delivery. No live collection or remote model upload is assumed from unit-test success.

## Completion and rollout

Code completion requires verified AC1–AC5 and evaluation tooling implementing AC6 correctly. Broad assist rollout separately requires >90% exact accuracy on independently reviewed held-out eligible breaks, with missing predictions included and agreed sample-size/confidence targets met. Leave assist restricted/off if that evidence is not available.

Use local scoped commits when implementing; push, PR publication and merge remain subject to human authorisation. This request has not invoked the additional per-slice PR approval cadence of spec-driven-development. No deployment or push is authorised by design approval alone.
