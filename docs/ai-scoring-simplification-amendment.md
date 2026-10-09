# Local scoring simplification amendment

Status: approved by the user on 2026-10-06. Supersedes the transport, camera-alias and shipped evaluation-tooling portions of earlier designs.

## Goal and recommendation

Keep local AI scoring, recorded footage and a simple script to debug prediction-versus-user-score differences. Remove the standalone evaluation/dataset tooling for now. User submissions remain the expected values for debugging; verified accuracy and the >90% release target remain future validation work.

## Changes

- Keep JSONL session events, immutable predictions/comparisons, clean-play rules, local Ollama observation, optional bounded recording, corrections/undo and manual fallback.
- Keep the read-only mismatch debugging script and its safe snapshot reader.
- Remove synthetic demonstration replay, standalone review/export/evaluation, dataset import/cohorts/alignment/offline model replay, and the standalone camera metadata probe, plus their feature-specific documentation/tests. Preserve synthetic rules/integration fixtures and internal FFmpeg/ffprobe metadata extraction needed for recording/inference.
- Allow Flutter-to-companion HTTP on the trusted LAN with the existing bearer token. Certificates become optional. Plain HTTP exposes the token and scoring traffic to the network; document this in setup guidance. This removes mandatory TLS provisioning while retaining the existing ownership check.
- Remove camera alias configuration and session fields. Configure one RTSP URL directly in the companion environment; never send the credential-bearing URL through Flutter or persist it in session records. Preserve single-camera leasing and restart/source-change continuity invalidation.
- Keep the logging override: it intentionally suppresses the inherited request logger. Add an explanatory comment rather than restoring default access logs.

## Colour clearance

Continuous clean play already advances yellow, green, brown, blue, pink, black. Thus after reds, yellow and green have been cleared, brown is next. Add regression coverage and explain this behavior. Attaching observation halfway through a frame is deferred: absent balls in one image cannot establish the rules state. Retain the supported new-frame baseline and abstention after unresolved gaps.

## Validation

Verify HTTP Flutter/backend connectivity contracts, off/dry-run/assist behavior, token authentication, no alias/credential persistence, colour progression across committed runs, recording/comparison/debug behavior and removal of public tools. Run installed companion tests and applicable Flutter tests; QA independently reviews the result. No push, history rewrite or merge is included in approval of this design.
