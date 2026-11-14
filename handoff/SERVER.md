# SERVER (Codex): row S-15. Demo reset + cache warm script
Scope: scripts/demo_reset.py (new) only.
`python3 scripts/demo_reset.py <base_url> [--dry-run]` prepares the live site for judging:
1. List chats via the API and delete those whose title starts with "smoke-", "e2e-", "test" or "Voice in AR" from automated runs. Never delete other chats. With --dry-run, only list them.
2. Warm the answer cache: ask the demo questions from docs/DEMO.md (parse its question list) on their docs in a throwaway chat titled "warmup-<time>", then delete that chat. Answers repeat fast because the model cache is keyed on inputs.
3. Fetch every demo doc's scene, glb, usdz and page images once, to warm the CDN and disk.
4. Print a summary table with timings.
Pace calls to stay under the rate limit (≤25 writes/min). It needs no keys; never print secrets.
Done test: --dry-run against http://localhost:8000 (if up) or the deployed site works and lists the actions.
Do not commit. Append a RESULT: line.

NEEDS: S-15 requires DELETE /api/chats/{chat_id} (including related messages/answers/scene edits); absent in server/chats_routes.py and local OpenAPI. Script scope excludes server changes; real reset stops before writes until this endpoint exists.
RESULT: S-15 scripts/demo_reset.py implemented; python3 scripts/demo_reset.py http://localhost:8000 --dry-run passed (exit 0, 10.017 s): 1 deletion target, 7 parsed questions on 3 docs, 12 asset fetches planned; stdlib-only, 2.5 s request pacing, title recheck and finally cleanup. Mock checks passed for deletion scope/renames, missing-route no-write guard, failure cleanup, page enumeration and SSE errors. Real reset needs the missing chat-delete API above; no chats changed, no commit.
