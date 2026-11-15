ACC-UNITS — final/acc-units

Apartment membership now uses room-label points before polygon centroids. Unit tags support the observed German/French prefixes and explicit multilingual vocabulary. Unlabelled nested room outlines toggle filled area with even-odd semantics; standalone unknown outlines retain their measured area with an Estimate card. Indoor totals exclude outdoor names. Written areas, computed net geometry, differences and written-precision cross-checks remain available.

| Check | Before | After |
| --- | ---: | ---: |
| sample200 correct / all rows | 138/200 | 139/200 |
| Swiss area correct | 15/18 | 16/18 |
| Swiss count correct | 28/39 | 28/39 |
| Correct-to-wrong regressions | — | 0 |
| sample200 errors | 0 | 0 |
| Focused synthetic/CAD/reasoning tests | — | 92 passed |
| Reserved blind numeric questions | unopened | 7/7 correct |
| Blind answer schema and proof checks | — | 7/7 passed |

All runs used MODELS_FAKE=1, one heavy job at a time through scripts/heavy.sh, with zero model spend. The current forbidden-ID list excluded documents before inspection/testing. The blind file was randomly reserved before implementation: `swiss_dwellings__site317-bldg647-floor2745`; it was first inspected only in the final check, after production code was frozen.

Development provenance: 12 Swiss drawings, 415 room outlines, 36 unit outlines, 34 apartment tags. All 36 unit rings close by repeating their endpoint without setting the DXF closed bit. Final private rebuild: 51 Swiss drawings, 34 nested void outlines, 171 unit records (164 with indoor room measurements; 160 labelled). Three unrelated CAD origins exercised unsupported-layer fallback; one has a pre-existing missing registration-text sidecar. Positive area recognition outside the explicit UNIT_OUTLINE convention is unverified. See constants.json, other-origins.json and research.md.

Limits: two Swiss area questions still disagree with gold; their totals include regions of unknown use and are explicitly estimates. No constants were tuned to those answers. Seven unit records have no indoor room membership and cannot establish an apartment area. Live-provider evaluation remains the integrator's gate.

Integration: merge both extractor and solver changes. Existing cached plan maps need rebuilding with the frozen extractor; shared artifacts were never rewritten. Use `pipeline.dxf_planmap.process(doc_id, output_dir, dxf_path)` with copied pages/text metadata and the DXF path resolved from the source document metadata (full dataset paths, not the CLI's preview-only default). All validation outputs were private. ACC-VALUE retains ownership of general answer.value plumbing; this branch's apartment answers already carry numeric values.

CROSS-FILE: pipeline/dxf_planmap.py; new pipeline/dxf_units.py; engine/solvers/solve.py (apartment hook); new engine/solvers/apartment.py; new engine/tests/test_apartment_units.py. No PDF ingestion, model, prompt, contract or dependency changes.

NEEDS-AWAIS: none.

NEEDS: rebuild cached DXF maps and run the integrator's measurement-only/live-provider gates after merging. Do not infer accuracy for unknown room uses from a geometric sum.

Verification command: `MODELS_FAKE=1 /Users/akshatthapa/Workspace/junction/.venv/bin/python -m pytest engine/tests/test_apartment_units.py engine/tests/test_swiss_dxf.py engine/tests/test_reasoning*.py -q`. sample200 reports and per-row before/after outcomes are adjacent JSON/JSONL files; the after run uses isolated rebuilt plan maps and unchanged source sidecars.
