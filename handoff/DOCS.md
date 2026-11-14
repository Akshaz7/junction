# DOCS (Codex) — current row

ROW: X-15 report refresh
Goal: bring docs/REPORT.md, docs/MODELS.md and docs/JUDGES.md in line with the current engine/models/models.yaml chains: Claude Sonnet 5.5 (via Runware's Anthropic-compatible /v1/messages) for written answers and chat, Fable 5.2 for recount boxes, Gemini 3.1 Flash-Lite via Runware for cheap recount and forced answers, Nemotron for route/advisor/scene intent, ElevenLabs for TTS, Verda Nemotron VL last (slow). No direct Gemini/Anthropic keys in production. Remove any claim not backed by results/. Mention: no abstentions (e-s200-z1 76.47%, 0 abstentions), headline count always equals numbered boxes (E-25), thread memory in chat, cross-device live sync, AR build-up + voice.
Done test: every number in the three files has a link to a file in results/ that contains it (write a small check script in scratch, print PASS/FAIL per number).
Edit only: docs/, this file.
Write one line at the end: RESULT: ...

NEEDS: LEAD reconcile X-15's Fable recount_boxes requirement with the concurrently updated models.yaml, which now selects claude-opus-5-5; docs follow the actual YAML and name the discrepancy. No engine/config changes made by DOCS.
RESULT: X-15 refreshed docs/REPORT.md, docs/MODELS.md and docs/JUDGES.md; .venv/bin/python docs/scratch/check_report_numbers.py PASS (32 quantitative literals linked to exact results JSON fields; all 17 current task chains match YAML). Identifier/version digits are metadata, checked separately from measurements. Unsupported upload timing and provisional prices removed; zero-abstention scope, E-25 boxed-count consistency, thread memory, live sync, AR build-up/voice and pending device rehearsal documented. No commit.
