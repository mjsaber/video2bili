# Growth and publication reliability implementation plan

User approved the review recommendations on 2026-09-05. Implement in the existing working tree, preserving pre-existing edits.

Goal: Make publishing recoverable, retain evidence for growth decisions, and enable shorter, evidence-led videos.

Architecture: Durable per-project publication receipts and a small archive under assets/publications; independently defined editorial chapters; topic evidence and relative traction; offline metrics import plus optional read-only Analytics collection. Existing CLI patterns and pytest remain the interface.

- [x] Publication: add atomic successful-upload receipts, file fingerprint and channel checks, resume thumbnail/playlist steps without duplicate upload, explicit recovery for uncertain uploads, archive lightweight artifacts. Regression tests must reproduce duplicate retry and failure after video creation.
- [x] Cleanup: only completed receipts qualify; order by upload time, archive before deleting, revalidate at execution. Metadata-only drafts never qualify. Preserve manual topic history and scan durable archived scripts.
- [x] Merge: accept one or more valid positive-length segments; keep media validation, define chapters independently via a file; invalid automatic chapter layout omits chapters without rejecting video. Test short hooks, single-source videos, valid and invalid explicit chapters, real ffmpeg.
- [x] Topics: normalize views for age and streamer baseline; retain evidence/confidence/version fields and candidates for review; avoid converting all-source errors into empty success. Keep pair policy, abstain on unknown core cards, expose review status. Regression tests use deterministic times and evidence.
- [x] Growth: CLI to import dated video metric snapshots and report 24h/7d/28d followups, traffic-source comparisons, subscriptions per thousand views, unavailable values as unavailable. Optional Analytics API read uses dedicated analytics scope/token and confirmed publication IDs; never fabricates impressions/new viewers from public views.
- [x] Production: update README, CLAUDE and SOP consistently for short result-first hooks, evidence-backed claims, decision-led editing, earlier contextual CTA/end screens, independent chapters, title/thumbnail experiments and scheduled review checkpoints. Expose configurable thumbnail layout and persist variant manifest; do not run live experiments or reupload existing videos.
- [x] Verification: focused red/green tests for each behavior, full pytest, CLI help/smoke, independent code review, inspect final diff. No production uploads or deletion of user artifacts during testing.

## Verification outcome

2026-09-05: full pytest 775 passed; git diff --check and compileall passed; all new CLI help commands ran through uv. Real ffmpeg tests verified short single-segment merge, timed CTA visibility, preserved video duration and unchanged audio packets. Brand/payoff thumbnails and 320x180 previews were rendered and visually inspected. Analytics import/report ran end-to-end with temporary synthetic data. Independent review findings on deletion ancestry/locking, adoption chronology, custom metadata archives, failed thumbnail preservation and empty measurement checkpoints were reproduced and fixed with regression tests. No real uploads, destructive cleanup, live A/B tests or OAuth collection were run.
