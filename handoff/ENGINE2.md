# ENGINE2 (Codex) — current row
ROW: E-48 opening_design remaining classes: wall-finish and area routes (see results/qa/od-failures.md from E-41)
Same method as E-41: fix the next 2 failure classes in code ($0) where possible; develop on non-held-out docs only (data/sets/heldout_docs.txt); single frozen before/after on held-out rows -> results/qa/od2-before-after.json.
Never return a confident wrong number; code-layer abstentions only when the production ladder still answers that route.
Allowed: engine/ (schedules.py, titleblock.py, text modules), engine/tests/test_od_pdf.py, results/qa/od2*, this file. Call-site lines only in engine/answer.py. ENGINE-ACC and ENGINE-CHAT are editing engine/answer.py edit/follow-up parsing now: do not touch those parts.
Done test: .venv/bin/python -m pytest -q engine/tests/test_od_pdf.py -p no:cacheprovider passes + the before/after file exists.
Never commit. Write one line at the end: RESULT: ...

NEEDS: LEAD record in LESSONS.md: generated schedule fixtures cover rotated headings, mirrored room-number checks and strict printed area units; E-48 frozen held-out coverage stayed 1/3, so do not claim a production accuracy gain or tune further on that drawing.
RESULT: E-48 done test passes (40 tests; 60 with titleblock); hardened wall/area schedule parsing and verified reader/forced fallbacks on generated for demo PDFs; results/qa/od2-before-after.json records one frozen $0 evaluation: numeric 1/3 before -> 1/3 after, zero wrong code answers, wall/area still defer; no engine/answer.py edits, no commits.
