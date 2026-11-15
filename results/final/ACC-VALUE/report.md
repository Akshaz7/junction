ACC-VALUE — PASS (fake-provider development checks; independent live gate pending).

Solvers retain computed numeric fields, including zero. Apartment sums resolve explicit source labels inside unique same-page unit outlines; unknown room shapes are flagged. Generic parenthetical room synonyms no longer become literal room names. Reader recovery requires a cited, typed computation and one matching headline number; measurements or fractions cannot become object counts. Unsupported numeric claims are withheld.

| Eligible rows | N | Correct before → after | Wrong before → after | Abstained before → after |
|---|---:|---:|---:|---:|
| sample200 | 200 | 138 → 139 | 30 → 31 | 19 → 17 |
| Relevant slice | 156 | 74 → 118 | 11 → 15 | 71 → 23 |
| Apartment areas | 50 | 13 → 46 | 1 → 4 | 36 → 0 |
| Rooms (spaces) | 86 | 52 → 63 | 7 → 8 | 27 → 15 |
| MEP counts | 15 | 7 → 7 | 3 → 3 | 5 → 5 |
| Zero counts | 5 | 2 → 2 | 0 → 0 | 3 → 3 |

sample200 additionally contains 13 unscored text rows. Zero correct-to-wrong or correct-to-abstained transitions in either comparison. Remaining mismatches concern source-room membership/quantities or fixture recognition; fake providers cannot reproduce live sauna readings.

Validation: 70 pytest cases; 12 source-consistency checks on three real-file origins plus the reserved blind file in `selection.json`. These diagnostics establish field/evidence consistency, not independent gold accuracy. No fitted symbol constants, prompt changes, new dependencies, live spend or forbidden-document access. All 745 checked structured sidecars predate the baseline, and final SHA256 fingerprints still match.

CROSS-FILE: shared hooks in engine/answer.py, engine/solvers/solve.py, engine/solvers/filters.py, engine/reader/agent.py, engine/reader/tools.py, engine/textqa.py.

NEEDS-AWAIS: none. NEEDS: integrate this branch and run the independent measurement-only/live-provider gates. No PDF ingest, model, split or benchmark scorer changes.
