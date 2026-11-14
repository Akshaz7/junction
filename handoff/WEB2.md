# Handoff: WEB2 (Codex, second worker)

Row ID: X-02 (attempt 1)  — sponsor pages (docs only)
Write `docs/sponsors/<tool>.md`, one page per tech-challenge tool that REALLY runs in the app today. Verify each by reading code + results files, never by assumption:
- Nemotron (engine/models providers + models.yaml route fallback; results/router_cost.json), Runware (provider for read_drawing etc.; results/costs.jsonl lines with provider runware), ElevenLabs (server/speech_routes.py /api/tts; web voice-controls), Modal (train/ or vision Modal scripts — only if a run actually happened: check COSTS.md / results), Aiven (Postgres hologram-pg; deploy notes), Codex (this build: WEB/3D/IOS workers via handoff files — describe the workflow from AGENTS.md), Gemini (only if a call with provider gemini exists in results/costs.jsonl; via Runware's google:gemini model counts as Runware, say so honestly), Cloudinary / Context.dev: only if code calls them (grep); otherwise NO page, and list them as "not integrated yet" in docs/sponsors/README.md.
Each page: what the tool does in our app (2–4 sentences, plain words per CONTRACT §5.8), where in the code (file paths + function names), numbers only copied from results/ files with the file named, one screenshot path placeholder `docs/sponsors/img/<tool>.png` (LEAD takes the screenshots), and the honest limits.
Then X-04: `docs/SUBMISSION.md` draft: project name "Hologram", punchline (≤12 words; pitch in CLAUDE.md), description (≤150 words), tech used, challenge list (only integrated tools), and a "numbers" block that only points to results/ files (LEAD fills the final numbers).
Rules: only docs/sponsors/ and docs/SUBMISSION.md. No keys, no Stoa logo/drawings, "Hologram" wordmark.
Done test (LEAD): one file per integrated tool, every claim traceable to a path; SUBMISSION.md exists.
Last failed attempt (if any): none

---
<!-- Worker appends RESULT: or NEEDS: lines below. -->
RESULT: X-02 and X-04 completed: docs/sponsors/{nemotron,runware,elevenlabs,aiven,codex}.md trace use to code and recorded evidence, include screenshot placeholders and honest limits; README records Cloudinary/Context.dev as not integrated, Modal as unproven, and Gemini-through-Runware as Runware with no direct Gemini log records. docs/SUBMISSION.md has Hologram, a 9-word punchline, 120-word description, evidenced challenge list and results-only number pointers. Local done-condition checks pass (tool-page set, links/paths, placeholders, word limits, exact quoted router/provider records); git diff --check passes. Screenshots remain for LEAD as assigned; no commit.
