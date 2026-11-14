# SERVER (Codex) — current row

ROW: S-28 wire the real Changes feed + spending cap + small hardening
1. server/files_routes.py: wire changes_source.visible_feed(pool, feed) into _feed after merging entries (before sort/group), and guard /changes/{id} with changes_source.visible_pair(pool, doc_a, doc_b) (helpers exist from S-25, committed e882db8). Test it.
2. The image has no COSTS.md, so engine/models/core.py caps() returns {} and prod has NO spending cap. COPY COSTS.md into the image (deploy/Dockerfile) and set ENV MODELS_COSTS_MD=/app/COSTS.md; /api/health adds caps_loaded: true/false.
3. engine/models/core.py _log(): wrap the costs-log write in try/except OSError so a read-only path never turns a paid call into an error (that one function only).
4. engine.findings.run() and engine.advisor.advise(): use the same artifacts root as the server (ARTIFACTS_DIR / config), not REPO/artifacts. Minimal change + test.
5. Chat message content length cap 8,000 chars → 413; doc_ids in POST /api/chats/{id}/messages validated against listed docs (unknown → 404, like /chats create).
Allowed: server/, deploy/Dockerfile, engine/models/core.py (_log only), engine/findings.py + engine/advisor.py (root resolution only), this file.
Done test: .venv/bin/python -m pytest -q -p no:cacheprovider server/tests (all pass; list any you deselect and why)
Never commit. Write one line at the end: RESULT: ...
RESULT: S-28 complete: Changes feed/detail filter listed and servable documents; image copies COSTS.md and sets MODELS_COSTS_MD; health reports caps_loaded; cost-log OSError is nonfatal; findings/advisor honor ARTIFACTS_DIR; messages enforce 8,000 characters (413) and listed doc_ids (404); regression coverage added. Done test `.venv/bin/python -m pytest -q -p no:cacheprovider server/tests`: 203 passed in 26.12s, none deselected; no commits.
