# PRD: AI-assisted break scoring — Phase 1

**Status:** Requirements approved by the user on 2026-10-04; technical design is the next review checkpoint.

**Problem and goal.** Players currently count and enter break points themselves. Use the mounted RTSP camera to estimate the points to add for a completed scoring run, reducing counting effort while preserving manual entry as the default. Integrate with the existing Flutter scoreboard’s additive break-entry flow. The player selects whose score to update; AI does not identify players or automatically change scores.

**Scoring basis.** A break consists of successive pots during one turn. Ball values are red 1, yellow 2, green 3, brown 4, blue 5, pink 6, black 7. Count each legally potted red, including multiple reds in one stroke. Alternate reds and colours, re-spotting colours; after the last red and its following colour opportunity, clear yellow through black in order without re-spotting. Re-spotting is not another scoring event. Example: red–black–red–pink = **15 points**. Source: [WPBSA official rulebook, Section 2 Rules 5/8 and Section 3 Rules 1/3](https://wpbsa.com/wp-content/uploads/2198_WPBSA-Rulebook-2024-25.pdf).

**Phase 1 features and acceptance criteria**

| ID | Required behavior |
| --- | --- |
| AC1 — Optional assistance | Keep manual input primary. When the player opens additive break entry, show a subtle AI icon and secondary action such as “Use AI score: 15” if an estimate is usable. Selection fills an editable value; explicit confirmation adds it once through the existing score/history flow. Suggest points to add, not the player’s cumulative score. |
| AC2 — Fresh scoring runs | Start observation at each new frame. A committed break entry, manual or AI-assisted, closes the run and starts a fresh zero-point run. Opening/cancelling input does not reset it. Existing grouped +1 taps form one entry; total-score edits, deductions, and undo are corrections, not independently scored breaks. Preserve the observed table state needed for red/colour progression across run resets. |
| AC3 — Configuration | Support `off`, `dry-run`, and `assist`; default `off`. Off performs no AI processing or collection. Dry-run observes and collects comparisons without AI UI or score changes. Assist exposes optional suggestions. Camera connection settings are configurable; credentials never appear in this document, UI, or dataset. |
| AC4 — Manual fallback | Missing feed, occlusion, ambiguous pots, or stale estimates must not block manual scoring or offer misleading values. A dropped observation interval cannot silently become a complete-break estimate after reconnect. Finish/session exit stops observation; a new frame cannot inherit an old suggestion. |
| AC5 — Learning data | For every committed break, record the prediction frozen before score input, submitted points, entry source, run timestamps, prediction availability/quality, model version, and links to limited reviewable visual evidence. Collect agreements and mismatches; flag mismatches for review. Manual entries are provisional labels. AI-accepted entries cannot establish independent accuracy; corrections/undo invalidate or revise affected labels. |
| AC6 — Launch evaluation | Require **>90% exact-score accuracy** on a held-out, independently reviewed set of supported clean breaks before broader assist rollout. Metric: exact predictions ÷ all eligible reviewed breaks; missing predictions count as failures. Report sample size, uncertainty, suggestion coverage, error sizes, and exclusion counts/reasons. Freeze predictions before observing submitted values. |

**Approved simplification (2026-10-06).** Phase 1 ships recording and a read-only mismatch-debugging script using submitted scores as expectations. Dataset import, review/evaluation, offline replay and camera-probe commands are deferred. AC6 remains a future release condition; its evaluator is not part of this delivery. HTTP on the trusted LAN is supported, pairing tokens retained, and the RTSP URL is configured only on the companion. See the [amendment](ai-scoring-simplification-amendment.md).

**Scope and assumptions.** Phase 1 assumes foul-free play; it does not certify stroke legality. Exclude foul penalties, free balls, re-spotted-black tie-breaks, player recognition, automatic score posting, and automatic model retraining. User input remains authoritative.

**Boundary limitation.** Official turns also end on non-scoring strokes. Submission-based resets are a Phase 1 proxy: delayed, omitted, or mid-break entries can split or merge actual breaks. Assume each scored break is entered before subsequent scoring begins; independently review boundaries and report violations separately. Automatic turn detection or an explicit new-visit action is a later scope decision.

**Architect handoff.** Choose VLM/computer-vision approach and processing location during design. Validate against the supplied oblique camera view, including small far-side balls, glare, clusters, and player occlusion; live RTSP quality has not been tested. Before collection/launch, settle evidence retention/access, suggestion freshness, and evaluation sample-size/confidence targets.
