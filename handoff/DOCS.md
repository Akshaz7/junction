# DOCS (Codex) — current row

ROW: X-18 demo reset check + licences
1. Read scripts/demo_reset.py. Make sure it removes test junk visible to judges (QA-LIVE results/qa/live-1439.md item 9: upload-fixture docs, "generated for demo" rows that aren't meant to be shown, chats titled "Cross-device ..." and other e2e chats), and never deletes real dataset docs. Add a --dry-run that lists what it would delete. You may edit scripts/demo_reset.py and add scripts/tests/test_demo_reset.py (sqlite or a mocked DB layer, no network).
2. docs/MODELS.md and README: licences table for every model and dataset we use (Claude via Runware, Gemini 4/3.x via Runware, Nemotron, ElevenLabs, RT-DETR detector + weights NC-SA due to CubiCasa, IfcOpenShell LGPL, three.js MIT, etc.). Check package.json and requirements for any GPL/AGPL dependency and list them (should be none).
Done test: .venv/bin/python -m pytest -q scripts/tests/test_demo_reset.py ; plus `.venv/bin/python scripts/demo_reset.py --dry-run` runs without a DB (prints "no DATABASE_URL" or lists).
Never commit. Write one line at the end: RESULT: ...

ADDED by LEAD (same row): docs/JUDGES.md (served in-app at #/help): replace the upload timing claim (QA measured 84 s for an A-801 PDF; give measured ranges only, with a link to the results file, or no number), and add deep links: "#/chat" plus 3 example questions written as #/chat?doc=ifc_bench__ac20-arc links, and #/data. Check that the help-markdown renderer allows hash links.

NEEDS: LEAD apply reset with DATABASE_URL explicitly exported, then recreate the deployed ephemeral API container to discard old upload files/persisted search index; DB cleanup deliberately leaves source/artifact files untouched. Use --keep-id for intentional generated rows. Unmarked titles such as Draft claim remain because they also identify real user chats.
RESULT: X-18 complete: transactional test-upload/generated-change/e2e-chat cleanup with dataset guards and --keep-id; 30 offline tests pass; DB-free --dry-run prints no DATABASE_URL; README/MODELS inventories cover hosted/local models and all dataset sources, no direct GPL/AGPL packages, with LGPL and SciPy GCC-runtime-exception notices recorded; no live deletions or commits.
