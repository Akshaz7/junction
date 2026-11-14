# ENGINE2 (Codex) — current row

ROW: E-39 Swiss DXF accuracy (weakest source in sample200: swiss_dwellings .684, results/bench/e-s200-z2.json)
1. From results/bench/e-s200-z2.rows.jsonl take every swiss_dwellings row graded wrong; group by question type and kind (doors, windows, rooms, areas, toilets …). Write results/qa/swiss-failures.md (counts per class, 2 examples each with gold vs ours).
2. For the top 2 classes, find the cause in the DXF plan map / solver (layer names, block names, units, double counting of door leaves, room polygons from hatches vs labels, area units mm²→m²). Fix in code (pipeline/ DXF reader or engine solvers), $0.
3. Rerun only the swiss rows of sample200 (python -m engine.bench supports a filter? check; otherwise a small script) and report before/after. Never touch held-out docs (data/sets/heldout_docs.txt) for tuning.
Allowed: pipeline/ (DXF reading only), engine/solvers/, engine/tests/, results/qa/swiss*, this file. Call-site lines only in engine/answer.py.
Done test: new tests in engine/tests/test_swiss_dxf.py pass + the before/after numbers file exists.
Never commit. Write one line at the end: RESULT: ...

NEEDS: LEAD/DATA may rebuild DXF plan maps with pipeline.dxf_planmap through scripts/heavy.sh to apply the reader changes to persisted artifacts; evaluation rebuilt both versions only in temporary directories. Anonymous FIXTURE symbols still need a non-held-out semantic source; the app reader/forced-answer fallback remains unchanged and can estimate after the code solver abstains.
RESULT: E-39 done — 45 targeted tests pass (13 new Swiss DXF regressions); paired $0 code-only Swiss sample200 39/57 (68.42%) -> 42/57 (73.68%), wrong 16 -> 3, abstained 2 -> 12 (abstentions count as wrong); all three room-label count failures fixed, ten untyped fixture zeros now abstain. Reports: results/qa/swiss-failures.md and results/qa/swiss-before-after.json; reproducible runner results/qa/swiss_rerun.py. Developed on generated-for-demo fixtures; held-out drawings used once for frozen evaluation only. No commits.
