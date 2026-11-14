# SERVER (Codex): row S-13. Upload robustness for judges' own files
Scope: server/files_routes.py, server/ingest_job.py (error paths only), server/tests/.
1. Upload limits: give a clear 413 JSON error above the size cap (read the current cap), a clear 415 for unsupported types (list the supported ones: pdf, png, jpg, dxf, ifc), and reject zero-byte files.
2. Ingest failures must set the ingest status to "failed" with a human-readable reason, never stay "running" forever. Add a watchdog: if a job is running longer than 5 min, mark it failed with "timed out".
3. GET /api/docs/{id}/ingest returns {status, step, progress 0..1, reason?}, so the web can show progress and errors.
4. Add tests for each case.
Done test: `.venv/bin/python -m pytest -q -p no:cacheprovider server/tests/test_files*.py server/tests/test_upload*.py`. If DB tests can't run in the sandbox, say so.
Do not commit. Append a RESULT: line.
RESULT: S-13 passed: scripts/heavy.sh .venv/bin/python -m pytest -q -p no:cacheprovider server/tests/test_files*.py server/tests/test_upload*.py — 35 passed in 8.83s, including PostgreSQL upload end-to-end tests. Added 100 MiB/empty/type validation, failed-ingest reasons, five-minute watchdog with process-group cleanup and stale-status recovery, and step/progress status fields. Changed server/files_routes.py, server/ingest_job.py, server/tests/test_files_upload.py; no commit.
