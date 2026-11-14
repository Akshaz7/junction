# Opening_design PDF failures — E-41

Source: `results/bench/e-s200-z2.rows.jsonl`. Gold is copied from the archive only; it is never supplied to the schedule reader.

| Class | Total | Wrong | Partial |
|---|---:|---:|---:|
| room finish schedule / all-four-wall predicate | 1 | 1 | 0 |
| opening schedule / room-mark count | 1 | 0 | 0 |
| room finish schedule / area lookup | 1 | 0 | 0 |
| room finish schedule / largest area | 1 | 0 | 0 |

## Failing examples (up to two per class)

### room finish schedule / all-four-wall predicate

- Document: `opening_design__sports-complex-sheets-current-set-a-801-door-and-finish-schedules-wall-types`
- Question: On sheet A-801 of the Xcel Sports Complex drawings, how many rooms have all four walls finished with W1 (painted gypsum board)?
- Gold: **6**; ours: **7**. Route: `hybrid`.
- Saved answer: **7** (low confidence: an estimate from the printed text and the drawing image, not measured).
- Only one failing example exists; no second example is invented.

## Scope and development

- 4 archived rows; 1 wrong/partial. 1 distinct document(s); 1 held out.
- There is only one failing class, so there is no second failure class to rank. The second development path is the neighboring door/window schedule room-mark count; its archived door question was already correct.
- Code fixes: require four separately headed wall cells per complete room record; match finish codes exactly; reject incomplete/merged/duplicate records. Match opening marks by explicit room column, or exact room-derived marks; honor explicit quantities.
- Room-area lookup and largest-area lookup share those records and preserve printed SF/m² units. The archived area answer has value 5183 labeled m²; its dataset score checks the number, not units.
- Development uses generated for demo PDFs/tables only. No held-out PDF, image, text artifact or plan map was inspected to choose the fixes. Title-block behavior remains E-35; no title/scale failure exists in these rows.
- A deterministic lookup returns None on unsupported/incomplete evidence. Production keeps running the reader and `_answer_forced` (`engine/answer.py`); generated integration tests cover both a reader answer and a reader abstention followed by the forced rung. Existing vision recount is not bypassed.
- The frozen evaluation compares deterministic code before/after, with the model-backed archive shown separately. Deferred rows count as incorrect; no archived answer is substituted for a fresh code result. It does not claim a new production/model accuracy measurement.

## Frozen evaluation result

- Comparable deterministic numeric correctness: 0/3 before → 1/3 after; no wrong numeric code answers. Evaluation cost: $0.
- The door schedule room-mark question is now answered by code with five exact records and six evidence boxes (whole table + five records).
- The all-four-wall count, room-area lookup and largest-area text question still defer. Their actual held-out layout is not used for further development after this frozen run.
- Archived model-backed numeric correctness remains 2/3. The code-only 1/3 is coverage, not a claim that production accuracy improved. Production reader/forced answers were not remeasured.
