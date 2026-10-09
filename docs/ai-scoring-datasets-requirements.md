# Functional addendum: recorded scoring datasets

> Historical document: the approved [simplification amendment](ai-scoring-simplification-amendment.md) supersedes transport, camera-alias and shipped dataset/evaluation tooling described here.
**Status:** Approved with the recording design on 2026-10-05, using local storage and reviewed offline improvement first. Automatic training remains outside this implementation scope.

**Goal:** Capture future play alongside timestamped AI predictions and submitted scores, creating reviewable datasets for reproducible evaluation and deliberate model improvement. Manual scoring stays authoritative and available throughout collection.

**Scope change:** Complete opted-in session recordings extend the approved limited evidence windows to session video. The existing implementation stores scoring metadata and reviews; video capture and visual inference are not connected yet.

| ID | Required behavior |
| --- | --- |
| DS1 — Recording configuration | Recording is independently configurable and disabled by default. When enabled, record an active scoring session through finish/recording stop, including frame boundaries. Dry-run collection exposes no AI scoring UI; the operator can inspect recording health. |
| DS2 — Aligned timeline | Link video and records using session/frame/run/entry IDs, media offsets, capture times, UTC mapping and clock uncertainty. Retain prediction creation/observation time, input-start and score-commit time. Unknown alignment, delayed delivery and uncertain boundaries remain flagged. |
| DS3 — Scoring provenance | Preserve each immutable prediction frozen before input, or explicit unavailability; submitted points, applied score delta, manual/AI-selected/AI-edited source and corrections/undo references. Retain agreements, mismatches and missing predictions. Later input never changes original predictions. |
| DS4 — Reviewed truth | Submitted scores are provisional. Independent review establishes actual points, supported-play eligibility, boundary validity and evidence sufficiency. AI acceptance alone never establishes correctness. Keep revision history. |
| DS5 — Import and replay | Import recording assets with their timeline and metadata, reporting missing assets or invalid alignment. Replay a recording against an identified model/configuration version without altering original results or the live scoreboard. Preserve sampling/inference settings and disclose nondeterminism where exact reproduction is unsupported. |
| DS6 — Improvement cohorts | Assign recordings to tuning or held-out evaluation before examining evaluation outcomes; keep related recording segments together. Improve using reviewed tuning examples. Replay inference receives footage and permitted boundary context, never submitted/reviewed score answers. |
| DS7 — Failure and storage limits | Configure retention/storage limits. Record camera gaps, missing/expired video, disk limits, interruption and recording failures as dataset-quality events. They never silently become complete examples or block manual scores. |
| DS8 — Honest evaluation | Report exact-score accuracy, eligible sample size, missing predictions, coverage, error sizes, uncertainty, exclusions, boundary violations and collection loss. Missing predictions count as failures for eligible reviewed breaks. Report held-out results separately; recordings/synthetic tests alone do not establish the >90% launch gate. |

**Example:** AI predicts 15 before input; the player submits 14. Retain both values, their timestamps and corresponding video span. Review might confirm 14, confirm 15 or mark the span ambiguous. Preserve that decision separately. In dry-run, the same comparison is recorded without exposing the AI prediction to the player.

**Proposed improvement loop:** collect -> review -> select tuning examples -> revise a versioned prompt/model/configuration -> replay -> evaluate against untouched held-out recordings -> human-approved rollout. Automatic retraining and autonomous changes to the deployed model remain separate scope decisions; collecting JSON does not itself update model weights.

**Pending choices:** companion host; full-session recordings versus event windows; configurable retention/storage/access; local versus external inference; reviewed offline improvement versus automatic training. Recommend local storage and reviewed offline improvement first. External transfer remains disabled pending an explicit choice.
