# Backend features on the live stack (skills, automations, findings, changes)

Checked 14 Nov 2026 ~12:05 against https://hologram-khaki.vercel.app/api, calls paced 3 s apart.

## Skills (POST /api/skills/{id}/run)
| Skill | Doc | Time | Result |
|---|---|---|---|
| Count on a plan | ac20 (IFC) | 3.3 s | 206 windows, 1 citation, route index, $0 |
| Find a room's area | ac20 | 2.5 s | total of 82 rooms = 1,939.4 m2, 1 citation |
| Locate something | ac20 | 41.9 s | names stair "Treppe-2-OG", 3 citations, hybrid route, $0.047 (slow: LLM) |
| Read a drawing | ac20 | 4.5 s | 77 doors, 1 citation, $0.004 |
| Count on a plan | CubiCasa colorful-11397 | 1.1 s | 11 windows, planmap, $0 |
| Find a room's area | CubiCasa | 0.5 s | 10 rooms total 93.7 m2, "approximate" flagged |

Notes: "Find a room's area" answers the TOTAL area of all rooms (the starter prompt says "this room", no room is chosen); ENGINE may want a clarifying answer. "Count windows" on ac20 says 206 here while the demo data shows 77 doors for doors: not cross-checked. One transient `not found` seen once on a first CubiCasa call, not reproducible.

## Automations
Create -> run (0.45 s) -> report.md -> report.pdf -> delete all worked live (next_run_at +24 h, 1-page PDF with extractable text, delete 204). Nothing fake: the report is the engine answer plus sources.

## Findings
- ac20: 3 findings, rule fi-fire-exits-per-storey (one exit on 1. OG, 2. OG, Keller), each with rule URL and quote, **message non-empty** (the earlier empty-message report is already fixed live; regression test added).
- CubiCasa plan: 0 findings (status ok): honest, no checks fired.

## Changes feed
List summary.source and detail source are both `pdf-diff` live (the earlier "truth"/"engine" mismatch is gone); regression test added.

## Fixed / added in this pass (server/)
- Scheduler: first tick 5 s after start (catch-up of runs that fell due while the container was down), then every 30 s. Runs are claimed with a compare-and-set on last_run_at, so two instances or a restart never double-run. All state is in PostgreSQL.
- Failed run report now includes the error text; report Sources lines no longer end in an empty "p.1:".
- PDF download (`/report.pdf`) already existed (stdlib writer, no licence issue): now covered by a test.
- Tests: test_skills_findings (+3), test_changes (+1).

## NEEDS (engine-side)
- ENGINE-FIX: "Find a room's area" with no room named should ask which room instead of summing all rooms.
- ENGINE-FIX: "Locate something" takes 42 s on ac20 (LLM route); consider a code route for "stair core on level N".
- Unrelated to this task: server/tests/test_contract.py::test_real_engine_answer_through_api and test_live.py fail/slow with the engine as currently edited (engine errors on an empty artifacts dir).
