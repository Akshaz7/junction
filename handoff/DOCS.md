# DOCS (Codex): row X-10. Demo script + submission docs
Scope: docs/DEMO.md, docs/SUBMISSION.md (new), README.md (top section only).
Read DECISIONS.md (last 40 lines), docs/MASTER_PROMPT.md (pitch + judging), results/ (numbers only from there) and docs/ACCURACY.md.
Write docs/DEMO.md: the exact click path for the live judging demo.
- Laptop: judge asks → 2D proof → 3D "Visualise it".
- Phone: same chat streams live → Show on table → AR build-up from the 2D plan → voice "show me the doors" → highlights spin in → voice turn appears on the laptop.
- The upload-your-own-drawing path, with a Plan B for each step (offline AR_DEMO build, recorded video, a backup question list).
- A 2-minute and a 5-minute version, plus the pitch lines: "We rebuilt Stoa's product in two days. Then we built the part that does not exist yet."
- Map every step to the 4 criteria (accuracy / visual verifiability / creativity / low inference cost).
Write docs/SUBMISSION.md: the checklist for the 10:00 submission (links, video, report, repo, licences).
Use placeholders for numbers that are not in results/ yet.
Do not commit. Append a RESULT: line.
RESULT: X-10 passed local documentation validation (links, required demo/upload/Plan B coverage, continuous 120s/300s shot budgets, candidate and sample200-r10 facts, README top-only scope) and git diff --check; updated docs/DEMO.md, docs/SUBMISSION.md and README.md top section; physical AR/build-up/spin/live-sync rehearsal and final submission links/metrics remain explicitly pending; no commit.
