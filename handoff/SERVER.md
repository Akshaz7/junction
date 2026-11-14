# SERVER (Codex) — current row

ROW: S-29 /ws hardening without breaking live sync
Today /ws accepts edits and broadcasts from any client, unthrottled and unscoped (Awais's review D-1). Fix, keeping every current live flow working (laptop→phone chat events, pairing, scene highlight/hide/reset commands, advisor cards, voice turns from iOS):
1. Per-connection throttle: max 20 inbound messages/s and 200/min; excess messages dropped with one {"type":"error","code":"rate_limited"} notice; frames > 64 KB rejected.
2. Inbound message types allowlisted (list them from server/live.py and the web/iOS senders: grep web/src and ios/Hologram for socket sends). Unknown types are ignored.
3. Scene edits/commands must reference a listed doc_id (servable list) and item ids that exist in that doc's scene manifest when one exists; otherwise reject with an error event.
4. Don't change event shapes; CONTRACT.md stays as is.
Tests: server/tests/test_ws_hardening.py (throttle, size, allowlist, bad doc id) + the existing test_live/test_pair suites stay green.
Allowed: server/live.py, server/ (helpers), server/tests/, this file.
Done test: .venv/bin/python -m pytest -q -p no:cacheprovider server/tests
Never commit. Write one line at the end: RESULT: ...
RESULT: S-29 passed — rolling per-connection 20/s + 200/min limits with one notice per throttled burst, >64 KiB text/binary close 1009, inbound allowlist (ping/pong/scene.join/scene.highlight/scene.edit), listed-document and local/DB scene-item validation; registered local docs retain no-DB sync; event shapes unchanged. Done test: 227 passed in 31.59s; no commit.
