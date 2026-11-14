# WEB4 (Codex) — current row

ROW: S-25 Changes feed from REAL revisions (no synthetic input)
Today the Changes feed is built from 3 synthetic v1/v2 pairs of Swiss DXF (server/changes_source.py, pipeline/revisions.py, payload generated_for_demo: true). Ash: everything live, nothing fake. The dataset has real re-issued sheets (results/parity_audit.md section 1 lists 14 multi-date series, e.g. opening_design__sports-complex-transfer-archive-20150811/12/13-restroom-markups…, ctr foundation markups 20190630/20190701/20190707, vacation-rental 20170517/20170518 s400–s403, crema-cafe a-100/a-101 v2).
1. server/changes_source.py: build the feed from those real series (consecutive dates within a series → one change entry: from_doc, to_doc, date, sender/recipient from the id, discipline). Use engine/changes.py (the real diff engine) for the diff where both docs have page text or plan maps; otherwise list the change as "New issue of <sheet>" with page counts and no invented details.
2. Remove the synthetic swiss pairs from the feed (keep the code path only if tests need it; never shown).
3. Only include docs that are listed (servable) on the deployed API; check server/artifact_store.py's servable logic (HIDE_EMPTY_DOCS).
4. Web Changes screen: shows the real entries; filters by discipline/type work; clicking an entry opens Compare with the two real docs.
Tests: server/tests/test_changes_real.py (series grouping from ids, consecutive pairs, no generated_for_demo in output); a vitest for the Changes screen rendering a real-shaped entry and opening Compare.
Allowed: server/changes_source.py, server/tests/, web/src/components/changes-screen.*, compare-screen.*, this file.
Done test: .venv/bin/python -m pytest -q -p no:cacheprovider server/tests/test_changes_real.py && (cd web && npx tsc --noEmit && npx vitest run)
Never commit. Write one line at the end: RESULT: ...

NEEDS: LEAD/SERVER: files_routes.py is outside WEB4 scope; wire the new changes_source.visible_feed(pool, feed) into _feed after merging entries (before sort/group), and guard /changes/{id} with changes_source.visible_pair(pool, doc_a, doc_b) for series/uploads. Helpers will use the same documents + HIDE_EMPTY_DOCS/servable_ids logic as /api/docs.
NEEDS: LEAD/WEB e2e owner: web/e2e/changes.spec.ts still asserts comparison.generated_for_demo === false; the S-25 live output now omits that field as requested, so assert the field is absent. This e2e file is outside WEB4 scope.
NOTE: Kept existing real PDF series/caches; added registry grouping fallback, strict real-pair cache validation, plan-map/text fallbacks, issue/page-count metadata, discipline filters, and Compare deep links. Shared API client rejects image:null, so the scoped screen adapter preserves metadata/text-only comparisons.
RESULT: S-25 scoped implementation passes the exact done test: 8 pytest tests, tsc --noEmit, 375 Vitest tests (60 files); existing Changes server tests also pass (15 total). No commit. Pending LEAD/SERVER integration: connect visible_feed/visible_pair in out-of-scope files_routes.py; pending e2e owner update of the old generated_for_demo assertion (see NEEDS above).
