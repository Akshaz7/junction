# DOCS (Codex) — current row

ROW: X-16 demo script and judge Q&A sheet
Goal: docs/DEMO.md becomes the minute-by-minute live demo script for Ash (laptop + iPhone): 1) laptop: open AC20, ask "How many doors are on the ground floor?" → numbered boxes in 2D → Visualise it (3D build-up with the step slider) ; 2) phone follows the same chat live; Show on table → AR plan appears, building rises; 3) voice "show me the doors" → spin + sequential highlight; 4) voice "remove the front door, is it still compliant?" → violation card 848/2017 §33; 5) back on laptop the AR turns appear in the chat. Include a fallback line for each step if something fails (e.g. AR_DEMO build, the recorded video), and the reset step (scripts/demo_reset.py). Also docs/JUDGE_QA.md: 15 likely judge questions (accuracy, cost per answer, how verifiable, hallucinations, what's ours vs off-the-shelf, model choices, licences, held-out split) with short honest answers, numbers only from results/ with links.
Done test: every results number linked (reuse docs/scratch/check_report_numbers.py pattern) PASS.
Edit only: docs/, this file. Never commit.
Write one line at the end: RESULT: ...

NOTE: scripts/demo_reset.py parses DEMO.md’s Exact question table; preserved and checked offline. Narrowest-door measurement exists only in recorded answer text, so the script links the response without inventing a numeric JSON value.
NEEDS: LEAD rehearse the exact AC20 ground-floor door question → numbered 2D regions, physical-iPhone reveal/voice/card delivery, and fill the local recording/build/chat details in docs/DEMO.md before presenting; recorded IFC answers alone do not establish those paths.
RESULT: X-16 complete: docs/DEMO.md has the timed AC20 laptop/iPhone/AR/voice/edit/return sequence, per-step fallbacks and reset procedure; docs/JUDGE_QA.md has 15 honest answers. python3 docs/scratch/check_demo_numbers.py PASS (20 measured literals linked to exact results JSON fields, 57 links, Q&A coverage and reset-table compatibility). No commits.
