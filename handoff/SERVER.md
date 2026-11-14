# SERVER handoff
ROW: S-32b fix the regression from S-32 (early SSE status)
server/tests/test_servable_docs.py::test_hidden_listing_lazy_restore_and_fast_refusal now fails: a chat message to a hidden/unservable doc returns 200 (stream starts) instead of the fast 404 refusal. Keep the early status event, but run the cheap synchronous validation (doc servable / exists / chat exists, request shape) BEFORE returning the StreamingResponse, so refusals stay real HTTP errors; only slow work (chat create/DB writes/doc load) moves after the first yield.
Done test (<60 s): .venv/bin/python -m pytest -q server/tests -p no:cacheprovider  -> all pass (239).
Write RESULT: one line at the end. Never commit.
RESULT: S-32b passed: chat/document visibility and request validation precede SSE headers; Thinking… still precedes document restoration/history/message writes; updated HTTP refusal and streaming regression coverage; .venv/bin/python -m pytest -q server/tests -p no:cacheprovider → 239 passed in 30.05s. No commit.
