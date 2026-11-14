# Live API stress harness (X-07)

Run from the repository root with the existing API on localhost:8000:

```sh
scripts/heavy.sh .venv/bin/python -m tools.stress.run --tag stress-r1
```

No server is started or stopped. This creates real stress-labelled chats and
uploads small existing dataset files into the local API. Model calls use the
engine model layer and its existing provider caps. Held-out inputs are used for
evaluation only. Generation outputs are labelled **generated for demo**.

Options: `--only a,b,c` (also `dataset,paraphrases,edge`), `--limit N` for smoke
runs, `--base-url`, `--timeout` (90 seconds per HTTP operation), and `--pace`
(0.15 seconds between requests by default). A 429 activates shared 2.1-second
pacing and respects Retry-After. The ten-chat test attempts one concurrent burst
if no rate limit has been observed; otherwise it retains request pacing.

Results are saved incrementally in `results/stress/<tag>.cases.jsonl` and
`results/stress/<tag>.json`. Reusing a tag overwrites that tag's output. Each
summary includes all failures, group completion, coverage, costs, wall time,
client and engine latency, and schema fingerprint. A limited run is explicitly
marked partial. Exit 1 means recorded failures or a budget stop; inspect the
artifacts. A response streamed as an SSE `error` counts as a crash even when its
HTTP status is 200. A missing final answer also counts as invalid.

To retry a failed group without repeating successful groups, use
`--tag <existing-tag> --only b --retry-existing`. This backs up the previous
artifacts before replacing that group's cases, retains the other groups, and
records the retry in the summary. The schema, API and seed must match. A backup
is never overwritten. Generation enforces ten unique variants and excludes the
original in the model-layer schema, so invalid output takes the configured
provider fallback instead of entering the committed paraphrase cache.

- **a:** Fixed-seed 300-question sample, every source × type represented,
  proportional allocation after guaranteeing each stratum. Messages include
  their exact dataset doc_id, including documents not registered in the picker.
  Uses `engine.bench.score` and `summarize` unchanged. Text is recorded, unjudged.
- **b:** Extracts chosen demo ledger questions plus the step-8 edit sequence from
  `docs/DEMO.md`. Generates ten distinct short paraphrases per question once via
  `engine.models.call("route", ...)`, persisting `paraphrases.json` incrementally.
  Numeric values and units must exactly equal the live original. If the original
  has no numeric value, text is recorded without a numeric-match claim.
- **c:** Edge inputs, language handling, injection attempts, document selection,
  two document types' edit sequences and persisted state, ten simultaneous chat
  tasks, two WebSocket devices, and each upload format plus a random-byte PDF.
  Clean upload 4xx or observed `doc.new` are accepted; successful upload does not
  prove ingestion correctness. Uploads run last to avoid ingestion competing
  with the question evaluation.

Every returned answer is checked against `server/schemas/answer.schema.json`.
The dependency-free validator implements every assertion currently used there
and rejects unsupported schema keywords, including on absent properties.
Evidence and citation rectangles are checked against PNG dimensions fetched
through the page-image API and cached per document/page. Missing images fail the
case rather than falsely passing unchecked evidence. Multi-document boxes use
matching citations to resolve their page document when possible.

Credential patterns and system-prompt patterns flag possible leaks. Matched
content is redacted before any result is written. This is a heuristic detector,
not a proof that all possible secrets or prompt disclosures are recognized.
Language checks similarly use an English word heuristic; inspect flagged cases.
No environment secrets are read, copied or printed by this harness.

Fast harness verification (no real provider or server calls):

```sh
.venv/bin/python -m unittest tools.stress.test_stress
```
