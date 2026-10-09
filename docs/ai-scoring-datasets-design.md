# Design extension: recorded scoring datasets

> Historical document: the approved [simplification amendment](ai-scoring-simplification-amendment.md) supersedes transport, camera-alias and shipped dataset/evaluation tooling described here.
**Status:** Approved by the user on 2026-10-05, with local storage and reviewed offline improvement first.
**Sources:** [Dataset requirements](ai-scoring-datasets-requirements.md), [approved architecture](ai-break-scoring-design.md).

## 1. Problem statement

Capture opted-in scoring sessions with timestamped predictions and submissions so future footage supports independent review, reproducible evaluation and deliberate improvement.

The current companion supplies JSONL metadata, scoring services, review/export commands, synthetic replay and a read-only media probe. Recording and visual inference remain unconnected. Complete-session recording extends the approved limited evidence windows: those windows cannot guarantee the full timeline needed for recorded-session replay.

Collection stays local by default and never blocks manual scoring. Host/model selection, external inference and automatic training remain unresolved. The proposed default is reviewed offline improvement; this extension authorises no autonomous deployed-model changes.

## 2. Functional specs

DS1–DS4 and DS7 cover recording configuration, aligned timelines, immutable provenance, independent review and collection failures. DS5–DS6 add proposed import/replay and tuning/held-out cohorts. DS8 preserves honest evaluation.

Recording is independently enabled and requires an active observer mode (`dry-run` or `assist`). Off stops observation and recording. Dry-run adds no AI scoring controls; operator tooling exposes recording health.

## 3. Design choices

| Approach | Advantages | Limitations |
| --- | --- | --- |
| One session file | Simple playback | Abrupt termination affects finalisation; coarse cleanup. |
| Sequential video segments | Bounded files, incremental recovery and retention | Requires a timeline manifest; boundaries depend on stream/keyframes. |
| Event windows only | Lower storage | Omits context/missed events and cannot provide full-session replay. |

**Recommendation:** FFmpeg-managed segments with local files and JSONL manifests. Preserve the source stream where supported; select containers/transcoding after probing the camera. Segment duration is configurable, not an exact boundary guarantee. Reuse the single log writer; add no database, broker or distributed infrastructure.

## 4. Software architecture and API

### Capture lifetime and storage

Attach a recording worker to session ownership. Start when recording is enabled and the session acquires its lease. Finalise on recording stop, session finish, mode off, lease expiry or shutdown. Frame transitions add markers without restarting video.

Check expiry through an actual periodic worker, not only subsequent API requests, so an abandoned app cannot leave recording running indefinitely. The worker sends metadata through the existing single JSONL writer.

Store video under the session directory. Append `recording_started`, `segment_opened`, `segment_closed`, `capture_gap`, `recording_stopped` and `asset_expired` records. A closed segment includes:

```json
{
  "assetId": "asset-uuid",
  "relativePath": "video/segment-001.mkv",
  "observationEpoch": "epoch-uuid",
  "mediaStart": 0.0,
  "mediaDuration": 60.4,
  "captureStartUtc": "timestamp",
  "utcUncertaintyMs": 120,
  "alignmentStatus": "estimated"
}
```

Numbers illustrate the shape, not operating targets. Record codec/time-base metadata and finalised-file checksums. Unfinished/missing assets remain incomplete.

Configure retention, total storage cap and minimum free-space reserve before enabling recording. Delete expired closed assets with logged references; never silently remove an active segment. Unsatisfied limits stop recording and produce collection-loss records.

### Timeline and scoring provenance

Preserve presentation timestamps, segment offsets, service UTC/monotonic anchors, observation epochs and uncertainty. Receipt time is not necessarily exposure time; do not label it exact camera capture time.

Map client input/commit times using estimated clock offsets and preserve mapping uncertainty, late delivery and gaps. Evidence may identify an uncertain interval instead of an exact frame.

Each entry retains its frozen prediction ID or unavailable reason, input-start/commit times, submitted points, applied delta, input source and correction/undo references. Predictions retain creation/observed-through times. Scoring between freeze and commit remains boundary-uncertain.

Posthoc alignment appends versioned mapping/review records without replacing original timestamps or predictions.

### Visual adapter, import and replay

An adapter receives timestamped frames, calibration and permitted observation state. It returns ball observations, candidate pots/respots, confidence/ambiguity and a processed-through watermark. Identify model, prompt/configuration, sampling, calibration and adapter versions. Without an adapter, predictions stay unavailable.

Import validates manifests, relative paths, checksums, timestamps and missing assets in an isolated dataset namespace. It never submits events to the live scoreboard.

Replay selects an identified adapter/configuration and saves new results separately. Provide footage and permitted boundary context, excluding submitted/reviewed scores, correction values and original AI totals. At each entry cutoff, only preceding footage can inform its prediction; later respots cannot retrospectively improve an earlier answer.

Preserve runtime settings/nondeterminism. Offline replay cannot erase live missing predictions or prove that a live suggestion was available in time.

### Review and improvement

Persist tuning/held-out assignments before inspecting evaluation outcomes; keep related sessions/segments together and reject cross-cohort reuse.

Independent review first establishes actual points, eligibility, boundaries and evidence sufficiency without showing score answers. Submissions remain provisional.

**Proposed loop:** collect -> review tuning examples -> manually revise a versioned adapter/prompt/configuration -> replay -> evaluate untouched held-out recordings -> human-approved rollout. Automatic training and deployment are separate decisions.

## 5. Failure scenarios

Camera gaps create missing intervals. Disk exhaustion stops recording without affecting scoring. Worker crashes leave flagged unfinished assets; restart begins a new epoch. Uncertain clocks prevent exact-alignment claims. Missing assets block unsupported reviews/import examples.

Keep secrets out of manifests, exports, subprocess diagnostics and app UI; restrict capture-process/local-file access. External transfer remains disabled.

Before collection, choose recording limits/access/retention and confirm host capacity/camera compatibility. Before replay rollout, settle model settings and evaluation sample/confidence targets.
