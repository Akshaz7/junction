# SERVER (Codex): row S-12. Judging-day hardening
Scope: server/ratelimit.py, server/app.py (middleware config + health), server/tests/.
1. Make the rate limit configurable: RATE_LIMIT_PER_MIN, default 30. Exempt /api/health and GET static file routes (/api/docs/*/files/*, page images, /api/docs/*/scene), since a viewer loads many files at once. Also exempt the /ws upgrade. Keep 30/min on POST /api/chats*, uploads and /api/advise.
2. /api/health returns {ok, db, build_rev (env BUILD_REV), uptime_s, models_ok (any provider key present)}, with no secrets.
3. A tests case for each.
Done test: `.venv/bin/python -m pytest -q -p no:cacheprovider server/tests/test_ratelimit*.py server/tests/test_contract.py`. If DB tests can't run in the sandbox, say so.
Do not commit. Append a RESULT: line.
RESULT: S-12 passed: configurable RATE_LIMIT_PER_MIN (default 30), GET health/viewer assets and WebSocket upgrades exempt, writes still limited; health reports DB/build/uptime/provider-key availability without secrets. Done test: 50 passed in 1.67s (DB tests ran); existing test_health.py: 4 passed in 0.93s. Files: server/ratelimit.py, server/app.py, server/tests/test_ratelimit.py, server/tests/test_health.py; no commit.
