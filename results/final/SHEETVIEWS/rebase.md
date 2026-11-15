F-SHEETVIEWS rebase integration — 15 Nov 2026

Merged origin/main 5accd02 into final/sheetviews without rewriting history. Kept main's combined scale selection/proof and per-page rescaling, user-marked inventory, confidence rework, room fallback, sheet compare/wipe components and viewer tools. Added only the mixed-view count/evidence hooks and view overlay on top. Printed ratio evidence uses the shared spatial parser so fractional/decimal denominators retain their exact values in main's proof system. Count cards retain the separate Plan views evidence after the new count invariant runs.

Validation: TypeScript passed; 10 targeted web tests passed (view overlay, sheet compare, compare screen); 312 Python tests passed across sheet views, scales/proofs/policy, answers/solvers/reader, reasoning, units and server scale evidence. One inherited test fails on both untouched origin/main and this branch: engine/tests/test_scales.py::test_end_to_end_detail_area_and_measured_card (missing legacy measured-card wording). This integration leaves that main behavior unchanged.

MODELS_FAKE sample200 used independent artifact-sidecar copies for main and merged code. Both: 137 correct, 30 wrong, 20 abstentions, 13 unscored, 0 errors. All 200 values, outcomes, routes and box counts unchanged; two answers add view-scope text. Zero correct-to-wrong (or other noncorrect) regressions. Raw runs: sample200-rebase-main.json and sample200-rebase-merged.json; comparison: rebase-validation.json. No live model calls, shared-artifact rewrites, node_modules, or PDF-ingest edits.

CROSS-FILE added during integration: engine/reasoning.py (five-line hook preserving view-scope evidence after main's count invariant). Other owned/shared paths remain as listed in the initial RESULT.
