# DOCS (Codex) — current row

ROW: X-19 final report draft to submission quality
docs/REPORT.md is due Sun 08:30 (Finland). Make it the submission version now (it will be refreshed with final numbers later):
- Structure for the 4 judging criteria (25% each): accuracy, visual verifiability, creativity, low inference cost. One section each, with the strongest honest evidence and links into results/.
- Accuracy: sample200 e-s200-z1 (76.47%, 0 abstentions), the judge set (results/qa/judge_run-r4.json: 47/48 locally; say clearly it's our own 48-question set with code-computed gold), recount calibration tables (results/rc_*.json, results/recount_calib.json). Say what's NOT measured.
- Visual verifiability: numbered boxes = headline count (E-25), same numbers in 2D/3D/AR, citations; screenshots from results/e2e and results/qa/shots (pick 4, link them).
- Low cost: the code-first ladder; the cost per answer from results (check the bench JSON for cost fields); "$0 answers" share.
- Creativity: AR on the table with build-up, voice, live laptop→phone sync, Finnish rule checks after edits.
- Limits section, honest.
- ≤ 1,500 words. Keep every number linked; rerun your number checker.
Done test: python3 docs/scratch/check_report_numbers.py PASS (update it if needed).
Edit only: docs/REPORT.md, docs/scratch/, this file. Never commit.
Write one line at the end: RESULT: ...

RESULT: X-19 PASS — docs/REPORT.md submission version (1,019 visible words): four judging criteria, linked sample200 and internal local/deployed judge scores, recount tables, four inspected screenshots, cost and 69% zero-incremental-cost share, explicit limits; python3 docs/scratch/check_report_numbers.py PASS (64 quantitative literals). Checker recomputes allowlisted raw-result summaries and uses existing repo PyYAML when system python lacks it. Edited only REPORT.md, docs/scratch/check_report_numbers.py and this handoff; no commit.
