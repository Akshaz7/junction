# CX-ENGINE: FIX-13 filters, unsafe answers, comparisons and percentages
Rules: read AGENTS.md, CLAUDE.md, LESSONS.md, GOTCHAS.md first. Do NOT git commit/add/stash/checkout. Do NOT deploy or touch prod (Ash is demoing live). No per-document hard-coding: general code only (judges upload unseen files). Use .venv/bin/python for Python; heavy jobs via scripts/heavy.sh. FILES OWNED BY OTHERS RIGHT NOW (do not edit): engine/answer.py, engine/explain.py, engine/reasoning.py, web/src/components/answer-card.tsx, web/src/components/evidence-card*, pipeline/pdf_planmap.py, server/ingest_job.py. Source for every case: GitHub issue #1 on this repo (gh issue view 1 --comments), comments by Awais2805 at 17:24Z (priority list) and 17:27Z (test tables with case IDs, expected answers and what we said). Done test: listed per row; plus the existing suites stay green (MODELS_FAKE=1 .venv/bin/python -m pytest -q engine/tests server/tests --deselect server/tests/test_upload_e2e.py --deselect engine/tests/test_readdraw.py: 10 known failures in test_models.py are expected; web: cd web && npx tsc --noEmit && npx vitest run). When done append one line to this file starting RESULT: with what passed, what did not, files changed. Deadline 60 minutes; partial is fine, report honestly.

You own: engine/analytics.py, engine/textqa.py, engine/solvers/*, engine/units.py, engine/findings.py, and new tests in engine/tests/.

Rows (all on ifc_bench__ac20-arc unless noted; expected answers are in Awais's tables):
1. FIX-13: never answer an unfiltered total when the question names a filter. Return the filtered answer, or say plainly that the filter matched nothing and list the closest matches.
   - B05: "floor area of Besprechungsraum II" should give 24.75.
   - X24: "How big is the office?" (45 offices) should give the range, or ask which one.
   - X25: "area of the meeting room" (two Besprechungsraum) should give both.
   - X15: "area of the swimming pool" should say there is no such room and list the room types.
   - X14: "doors on the 5th floor" should say there is no 5th floor and list the storeys.
   - C05: "walls 300 mm thick" should give 67.
   - C07: "rooms larger than 20 m2" should give 39.
   - C06: offices on 1. OG between 12 and 25 m2 should list 5.
   - C08: labs in the basement plus their combined area should give [5, 59.1].
   - K01: "doros on the grund floor" should give 18. Fuzzy-match storey names (ground/grund/EG/Erdgeschoss, basement/Keller, 1st/first floor/1. OG) and room names (substring, umlaut folding, Roman numerals).
   - B03 and B04: largest and smallest room should give the room NAME (Seminarraum 128.3, Labor K5 11.1), not just "006 (Büroarbeit)".
2. Comparisons, percentages, ratios:
   - X18: "more windows than doors on the ground floor?" should say yes, 54 vs 18.
   - X20: "what percentage of doors are on the ground floor" should give 23.4%.
   - X21: window-to-floor area ratio on the ground floor should give 18.6%.
   - X19-style threshold questions should answer yes or no with the number.
   - Compute these in code from two solver results.
3. Unsafe or false-premise answers:
   - X12: "Since there are 100 doors…" should correct the premise (77).
   - X31: "remove all walls, is it compliant" should never say "No rule broken"; flag that structure is missing.
   - F01: an IFC model must never be called "a single floor plan".
   - X11: two selected models, "doors in total across both", should give 141 (sum per doc).
Done test: a new engine/tests/test_fix13.py covering each case above (MODELS_FAKE=1, real artifacts), with every listed case passing. Report pass/fail per case ID.

NEEDS: owner of engine/answer.py: call engine.analytics.multi_doc_total(question, doc_ids, root, t0) before the single-doc analytics/solver path and return a non-None result (preserving/emitting trace). Helper implemented in owned analytics.py for X11; dispatcher currently only supplies doc_ids[0]. Do not change CONTRACT.md.
NEEDS: C08 gold discrepancy: real net_floor_area_m2 sums Labor K1–K5 to 58.8984 m² (58.9), not 59.1; 59.1 results from rounding each room to one decimal before adding. Implementation preserves exact quantities and reports 58.9; do not hard-code the table value.
NEEDS: WEB/3D owner: required web checks tsc passes, vitest currently 450 passed / 1 failed / 9 skipped; src/viewer3d/__tests__/interaction.test.ts:79 expects camera.position.z exactly 20, gets 19.999999999999996. Outside CX-ENGINE ownership; no web files changed.
RESULT: PASS B03, B04, B05, C05, C06, C07, K01, X12, X14, X15, X18, X19 (yes/no threshold variants), X20, X21, X24, X25, X31, F01. C08: 5 labs passes; exact combined area is 58.8984 m² (58.9), so supplied 59.1 gold does not pass (round-before-sum discrepancy documented above). X11 blocked: public answer still returns 77; implemented/tested multi_doc_total helper returns 141 with both documents cited, but needs integration in separately owned engine/answer.py. New test_fix13.py: 37/38 pass, only public X11 fails; real artifacts, no fake data. Final required Python suites: 833 passed, 11 failed (10 expected test_models.py failures plus X11), 7 deselected, 46.03 s; prior tile/baseboard regressions fixed. Web: tsc passes; vitest 450 passed, 1 unrelated viewer3d failure, 9 skipped. Files changed: engine/analytics.py, engine/textqa.py, engine/findings.py, engine/solvers/solve.py, engine/solvers/filters.py (new), engine/tests/test_fix13.py (new), handoff/CX-ENGINE.md. No commits or deployment.
