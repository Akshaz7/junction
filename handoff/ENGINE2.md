# ENGINE2 (Codex) — current row

ROW: E-35 text questions on PDF sheets (dataset type "text")
data/junction-dataset-preview/questions.jsonl has text-type questions (answers are words, not numbers) on opening_design PDF sheets. Goal: answer them from the page text layer with exact quotes and citations, code first.
1. Pick 40 text questions on docs NOT in data/sets/heldout_docs.txt, with gold answers; save as results/qa/text40.jsonl (question, doc_id, gold).
2. Run them through engine.answer locally with MODELS_FAKE unset only if keys exist in .env; otherwise run with the fake provider and measure the code path only (say which). Grade: exact or normalised match, or gold contained in the answer. Save results/qa/text40-r1.json.
3. Fix the top failure classes in the text route (find it from engine/answer.py: page-text search, title-block fields like sheet number, scale, project name, drawn by, date, revision; note/legend lookup). Prefer code: title-block regexes and nearest-label lookup in the pdfminer text with positions. Every answer quotes the source text and cites page + bbox.
4. Rerun → text40-r2.json. Report before/after.
Allowed: engine/ (text route modules, a new engine/titleblock.py if useful), engine/tests/, results/qa/text40*, this file. Only call-site lines in engine/answer.py (others work there).
Done test: .venv/bin/python -m pytest -q -p no:cacheprovider engine/tests/test_titleblock.py (write it) and the r2 file exists.
Never commit. Write one line at the end: RESULT: ...

E-35 scope finding: registry files map all 265 preview text questions (16 opening_design PDFs, 249 IFC) to held-out docs. No eligible existing text questions remain. Using 40 questions labelled "generated for demo", with gold quotes/bboxes from 7 non-held-out PDFs; this measures development behavior, not dataset accuracy. Registry IDs include nested path slugs, so stem-only doc IDs give a false non-held-out result. All evaluation checks use actual doc.json IDs.
NEEDS: LEAD supply/authorize a non-held-out dataset text set if E-35 requires 40 existing dataset questions; the supplied split has zero.

NOTE from LEAD: engine/answer.py now imports engine.titleblock inside try/except ImportError (committed E-37). Your title-block route currently answers "What does note 4 on this sheet require?" with route "index" before the reader, which breaks engine/tests/test_reader.py::test_answer_routes_sheet_to_reader. Only answer title-block FIELDS (sheet no., scale, project, drawn by, date, revision); let note/requirement questions fall through to the reader. Run the whole engine/tests suite before RESULT.

E-35 validation: required done test 20 passed; r2 exists. Per LEAD, early routing handles title-block fields only; note/requirement questions still fall through to the reader (original reader test unchanged). Full engine/tests: 240 passed, 3 failed in test_readdraw; disabling titleblock reproduces the same three failures (220 passed excluding the 20 titleblock tests), while test_readdraw alone passes 4/4.
NEEDS: LEAD/ENGINE resolve existing full-suite ordering failures in test_readdraw.py (checked_region_becomes_citation, unbacked_regions_are_flagged, cannot_answer_and_no_image); reproduced with E-35 route disabled.
RESULT: E-35 title-block code route with verbatim quotes and page/pixel-box citations; generated-for-demo non-held-out text40 33/40 (82.5%, real providers, $0.037038) -> 40/40 (100%, 0 model calls, $0); done test 20 passed and text40-r2.json saved. Dataset accuracy unavailable: every supplied text question is held out. Full suite 240 passed/3 pre-existing ordering failures, reproduced with route disabled. No commit.
