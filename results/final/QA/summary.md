# F-QA judge checks

Runner verification: 22 passing tests; 120 public questions, 30 fixed-seed withheld questions; 13 development files across six dataset origins. A separately reserved random IFC is evaluated only after runner development. No engine or ingestion code changed.

| Run | Commit | Numeric correct / checked | Timeout limit | Provider-reported cost |
|---|---|---:|---:|---:|
| Recovered baseline (live) | `60efc46c0671` | 52 / 71 | 55 s | $0.640718 |
| Main (provider dispatch disabled) | `9d244d220e8e` | 51 / 71 | 20.0 s | $0.000000 |

These are constrained runs: provider requests were blocked by the budget/pricing guards, and private cached model responses can be reused. The different timeout limits and evolving cache prevent causal accuracy/latency claims. Expected=null questions check behaviour only. Numeric results and item-set hashes remain separate from formatting. Grading v2 flags source-item mismatches; earlier runs only recorded them.

## Final run and generalisation

Pinned main: `9d244d220e8e85f761743f365a66a4bcfbb22353`. [Final results](run-20261114T212016694190Z.md).

| Split | Questions | Numeric matched / checked | Fully passing checks | Timeouts |
|---|---:|---:|---:|---:|
| public | 120 | 52 / 71 | 36 | 0 |
| holdout | 30 | 16 / 21 | 5 | 1 |
| unseen | 12 | 9 / 11 | 5 | 0 |

Final public accuracy is unchanged from the baseline (52/71). The question holdout shares development files; the reserved file `ifc_models__resbim-110-model` was opened after runner development and its 12 questions were evaluated only at the end. Runner hashes match before and after. Private results are aggregates only.

Completed 16 reports and 555 question evaluations. Session provider-reported spend: $1.520712; accounted including uncertain attempts: $1.908472, below the $3 row cap. Citation checks require item IDs, a region or a quote: document-only references for zero counts can fail this stricter evidence test even when the numeric answer is right.

## Committed branch checks

All branch runs block provider dispatch and have a 20-second question limit. The table compares exactly the same public numeric questions against the main constrained run. Different source commits/cache histories prevent causal attribution.

| Branch | Questions | Main numeric | Branch numeric | Numeric checked | Latest report |
|---|---:|---:|---:|---:|---|
| `final/mep` | 24 | 9 | 3 | 20 | [details](run-20261114T211300328625Z.md) |
| `final/props` | 37 | 33 | 24 | 35 | [details](run-20261114T211448354072Z.md) |
| `final/proj-engine` | 11 | 4 | 4 | 7 | [details](run-20261114T211616062241Z.md) |
| `final/changes` | 1 | 0 | 0 | 1 | [details](run-20261114T213008865490Z.md) |
| `final/order` | 20 | 5 | 0 | 8 | [details](run-20261114T211707722217Z.md) |
| `final/scales` | 9 | 0 | 0 | 0 | [details](run-20261114T211716835573Z.md) |
| `final/scansym` | 9 | 0 | 0 | 0 | [details](run-20261114T213010120339Z.md) |
| `final/mistakes` | 5 | 0 | 0 | 0 | [details](run-20261114T211758869473Z.md) |
| `final/perf` | 13 | 8 | 8 | 8 | [details](run-20261114T211804617909Z.md) |
| `final/robust` | 13 | 8 | 8 | 8 | [details](run-20261114T211819953240Z.md) |

Important public findings:

- MEP: segment-count questions can return lengths (e.g. 3,045 raw pipe objects versus a returned value of 2,075.11). Check noun-to-operation routing before merging.
- PROPS: some width/fire-rating queries return null even for explicit recorded-object counts; positive-width filtering differs from all-width filtering. Verify zero/missing-width interpretation before treating a boundary failure as a product defect.
- ORDER: the explicit "recorded count plus 10%" calculation abstains on eight numeric cases in the tested branch; five were numeric matches on the constrained main replay.
- PROJECTS: the tested cross-discipline total reaches the 20-second limit. CHANGES: the one public before/project count difference fails; the second question is withheld.
- SCANSYM/SCALES/MISTAKES: the selected raster/DXF/DWG questions have no independently certified numeric answers. Passing a behaviour check cannot certify their accuracy.

Each run Markdown contains the top 15 public failures with owning area. Private prompts, expected values, answers and individual failures are withheld. The private question holdout shares development files; the separately reserved unseen-file check is the file-level generalisation check.

## Integration

Git staging/commits are blocked in this session: creating `.git/worktrees/qa/index.lock` was denied by the sandbox. Work remains on `final/qa` after WIP `aa436a771bd1`. The integrator must stage the exact owned paths (`scripts/judge_hard.py`, `results/final/QA/`, and force-add the ignored `engine/tests/data/judge_hard.jsonl`) and commit with an `F-QA:` message. Never stage the untracked shared symlinks.

Fresh upload ingestion, web/3D/AR behaviour and an independent raster tally are outside what `engine.answer.answer` over existing artifact copies can establish. No Awais/PDF changes are needed.
