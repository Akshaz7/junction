# ENGINE2 (Codex) — current row

ROW: E-33 project-wide questions search every doc with data (QA-LIVE #3, results/qa/live-1439.md)
Today, questions with no doc selected search only ~22 docs:
- "Which drawings have a door schedule?" says none, but at least 18 opening_design docs have "schedule" in the id and title (e.g. opening_design__aalseth-residence-...-a600-...-schedules, opening_design__ctr-most-current-set-full-size-sheets-a700-schedules).
- The kitchen list includes upload-fixture junk and misses AC20 (IFC spaces named Küche) and the Swiss plans.
Fix in engine/project_index.py (and whichever engine module answers project-wide questions, find it from engine/answer.py):
1. The index covers every listed doc with data: titles and ids (tokenised, e.g. "a600 schedules"), page text, plan-map room labels, IFC space names (LongName) and element kinds. Find why only ~22 are indexed (build step? only baked artifacts?) and fix it; say how deployed builds the index (deploy/Dockerfile runs `python -m engine.project_index build`).
2. Exclude uploads whose id contains "upload-fixture" and docs with generated_for_demo, unless the user selected them.
3. Synonyms: kitchen = Küche/kök/keittiö; WC/toilet; schedule = table/list on schedule sheets.
4. Answers list docs with one citation each (doc title + page), capped at 15, with "and N more".
Tests in engine/tests/test_project_index.py with a tmp artifacts tree: schedule question finds the schedule docs by title; kitchen finds an IFC Küche space and a plan-map "Kitchen" label; fixtures excluded.
Allowed: engine/project_index.py, the project-wide answer module, engine/tests/, this file. Do not edit engine/answer.py beyond a call-site line (others work there).
Done test: .venv/bin/python -m pytest -q -p no:cacheprovider engine/tests/test_project_index.py
Never commit. Write one line at the end: RESULT: ...

NOTE from LEAD (mid-row): ENGINE-FIX already changed engine/project_index.py and engine/project_answer.py (committed in E-34: synonym hits, test junk excluded). Build on that version; don't revert it. Your remaining scope: index coverage of every listed doc with data (titles/ids, page text, plan-map labels, IFC space names), and the door-schedule question finding schedule sheets by title.

Deployment: deploy/Dockerfile already runs `python -m engine.project_index build` over deploy/demo_artifacts (currently 22 document directories, no registry). PostgreSQL dataset artifacts are restored later; server/app.py only explicitly upserts uploads. Index v3 now discovers restored dataset directories on load and refreshes changed directory contents (at most five seconds between scans), and builds registry title/id records even before their files arrive. Rebuild existing v2 indexes with the same build command; no deploy/server edits needed.
NEEDS: DATA/LEAD: current artifacts/ifc_bench__ac20-arc/elements.json has no Küche/kitchen/kuche/kueche room name; check source/enrichment before expecting AC20 in kitchen results. Retrieval supports actual IFC LongName values; it does not invent missing rooms.
NEEDS: LEAD: record the lesson that the image-build index sees baked files only and startup restoration previously reindexed uploads only; dataset restores need index discovery too.
RESULT: E-33 PASS — required test_project_index.py: 9 passed; existing project_search/context_tasks: 19 passed. Covers registry metadata, restored dataset discovery, page text + plan-map labels + IFC LongName/kinds, multilingual synonyms, fixture/demo exclusion, one citation per document, 15-result cap and remaining count; empty lists skip the reader via one answer.py call-site line. No commits.
