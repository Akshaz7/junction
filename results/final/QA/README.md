# Complex-file judge checks

`engine/tests/data/judge_hard.jsonl` contains 120 public questions. The fixed-seed
20% holdout (30 questions) stays in the private temporary session directory;
`corpus.json` lists its IDs and digest, never its question text. A separately
reserved random real file is opened only after runner development. Its results
are reported as `unseen`, separately from the question holdout.

The 13 development sources cover large architectural, services and structural
IFCs, a second IFC source, a before/project pair, two DXFs, two raster scans and
a DWG. Selection is recorded in `selection.json`. IFC expected values come from
raw ifcopenshell queries, independent of the engine/index. DXF, raster and DWG
questions have no numeric oracle; passing their behaviour checks does not
establish accuracy. Two scans were visually inspected without inventing counts.

Run from this worktree using the shared Python environment:

```sh
MODELS_FAKE=1 .venv/bin/python scripts/judge_hard.py self-test
scripts/heavy.sh .venv/bin/python scripts/judge_hard.py build
scripts/heavy.sh .venv/bin/python scripts/judge_hard.py run --revision main --max-usd 1
scripts/heavy.sh .venv/bin/python scripts/judge_hard.py run --revision final/mep --owner MEP --max-usd .15
scripts/heavy.sh .venv/bin/python scripts/judge_hard.py matrix --mode code --max-usd 0 --timeout 20
scripts/heavy.sh .venv/bin/python scripts/judge_hard.py watch --interval 3600 --cycles 1 --mode code --max-usd 0 --timeout 20
scripts/heavy.sh .venv/bin/python scripts/judge_hard.py run --resume RUN_ID --max-usd 1
scripts/heavy.sh .venv/bin/python scripts/judge_hard.py unseen
scripts/heavy.sh .venv/bin/python scripts/judge_hard.py run --include-holdout --include-unseen --max-usd .5
```

Resume requires identical case selection, timeout, mode and budget. Source code
and artifact JSON are snapshotted privately. Each question has a process-group
timeout. Live calls still go through `engine/models.call()`; a QA adapter guard
reserves estimated costs before dispatch. Unknown prices and excess budgets
are blocked. Failed/interrupted requests retain their reserves. The session
cap is $3; per-run caps cannot exceed $4. These are estimated-price protections,
not a provider billing guarantee. Public records include per-question cost
deltas; the first 58 recovered baseline rows predate those fields and only have
the engine's reported answer cost. The shared ledger retains aggregate costs.
`code` mode blocks provider dispatch; existing private model-cache responses can
still be reused. It is not an assertion that no model response influenced an
answer. `matrix` checks committed branch tips on the subsets in `branch-plan.json`;
`watch` repeats that sweep after each interval and skips unchanged tips.

JSON and Markdown reports separate numeric accuracy, abstention, evidence,
reasoning/confidence, jargon and formatting. A source citation must include
item IDs, a region or a quote; a document-only citation for a zero count can
therefore fail this stricter evidence check even when its value is correct.
The raw citation count is retained separately. Holdout/unseen prompts, values,
answers and individual failures are never published. Reports record the exact
commit, case digests, artifact digests, runner hash and blocked calls; a run with
blocked model calls is a constrained run, not an unconstrained live benchmark.
Grading version 2 makes a mismatched source-item set a failing check. Earlier
runs recorded that field without adding a failure; compare numeric accuracy
and the raw evidence field across these versions, not total passing counts.

No engine fixes, source ingest changes, shared artifact writes or production
requests are part of this worker. Engine-only checks cannot validate web, 3D,
AR, upload ingestion, or independently certify raster symbol accuracy.
