# DECISIONS

Format for new lines: `YYYY-MM-DD HH:MM — decision — reason`.

## Fixed (section 2 of MASTER_PROMPT; do not reopen)
- Language: English only. Non-English questions filtered out of tests; drawings may contain other languages, app answers in English.
- Accounts: none. One shared demo workspace.
- Security: no security reviews, code reviews or CI. Only: keys never in git; rate limit 30 req/min/IP on deployed backend.
- Hosting: web on Vercel; backend (API + live sync) one container on Aiven Runtime; Aiven PostgreSQL; EU region.
- Local first: `make dev` runs everything with no keys (Docker Postgres, fake provider). Deploy rows wait for keys.
- GPU: Modal for fine-tuning and optional vision endpoints. Budget cap in COSTS.md.
- Budget provider: Runware (OpenAI-compatible) is main paid provider for bulk tests and fallback for every other provider.
- Gemini: called directly (Google challenge): reads drawings, checks unclear items, voice to intent.
- Nemotron: called directly on build.nvidia.com (NVIDIA challenge): router fallback, advisor, cheap item checks. Not wall detection.
- Claude: final written answers for text questions and hard reasoning.
- Small vision models: fine-tuned at the event: one segmenter (walls, doors, windows, rooms), one detector (doors, windows, toilets, sinks, showers, bathtubs).
- Verda: out (domain down). Do not call.
- Advisor rules: Finnish building rules in English translation; unofficial translations marked.
- Demo building: `ac20_arc.ifc` for IFC. Best DXF and raster plan chosen by test results.
- Dataset: preview first; full 10 GB in background.
- Agents: 7 workers under one Claude lead: 4 Claude (DATA, VISION, ENGINE, SERVER), 3 Codex (WEB, 3D, IOS). Lead runs every done test.
- Scope order: three tiers. Nothing is cut; order decides what finishes first.

## Log
- 2026-11-14 02:45 — LICENSE copyright changed to "2026 Team RS3" — section 11 requires it.
- 2026-11-14 02:45 — Initial TASKS status: rows with no keys `todo`, rows naming keys `waiting-key` — check_keys.py releases them.
- 2026-11-14 02:55 — Ash: build every iOS row (I-01..I-09) overnight against the simulator and unit tests; no device tonight. I-05 (install on iPhone) is deferred to Saturday morning when Ash plugs in the phone: the lead writes the exact install steps to MORNING.md and sets I-05 `blocked-human` instead of spending attempts on it. Device absence never counts as a failed attempt for any other iOS row — Ash's instruction.
- 2026-11-14 02:50 — Runware cap raised from 300 to 500 USD — Ash's instruction.
- 2026-11-14 02:51 — LEAD runs `git push origin main` right after every commit (never force; on rejection: `git pull --rebase origin main` then push; if that conflicts, abort the rebase, log it here and in MORNING.md, keep committing locally) — Ash's instruction, so progress is visible on GitHub.
- 2026-11-14 02:55 — Added row V-00 (model shortlist + CubiCasa5K download) — VISION has no row with satisfied deps until D-04. 3D waits for W-01 (~15 min) because T-01 needs the web scaffold.
- 2026-11-14 02:55 — LEAD owns root `pyproject.toml`/`uv.lock`; Claude workers request new Python deps with a NEEDS: line in their report instead of running `uv add` — avoids 4 agents racing on the lock file.
- 2026-11-14 02:55 — Codex runs as `codex exec -s workspace-write -c sandbox_workspace_write.network_access=true` (network for npm); iOS builds use `-derivedDataPath ios/build/DerivedData` so they stay inside the sandbox.
- 2026-11-14 02:56 — Added row T-00 (viewer core as plain TS, no package.json edits) — 3D had no row with satisfied deps (T-01 needs W-01 and D-06); Ash pointed out it was idle.
- 2026-11-14 02:57 — Pulse runs every 60 s in `scripts/lead_watch.sh` (logs/pulse.log); it wakes the LEAD only on a '!!' flag or every 10 min for check_keys. Worker completions wake the LEAD directly. Same 60 s pulse, far fewer idle lead turns.
- 2026-11-14 02:58 — I-02 starts before D-10 using a fixture USDZ the LEAD generates with usd-core (5 prims named by usd_name) — the row allows a bundled fixture; avoids IOS idling for hours. Real scenes swap in when D-10 lands.
- 2026-11-14 03:04 — T-01 starts before D-06 on the digital_hub fixture from T-00 — same reasoning as I-02; real ac20 scene swaps in when D-06 lands.
- 2026-11-14 03:05 — Router chain for task `route`: rules parser → NVIDIA Nemotron → Runware; Gemini removed from route — section 2 assigns the router fallback to Nemotron (NVIDIA challenge).
- 2026-11-14 03:08 — doc_id keeps the source folder name verbatim and slugs only the stem (`ifc_bench__ac20-arc`, `cubicasa5k__colorful-11397`); matches the CONTRACT 5.1 example. CONTRACT v2: doc.json gains `files` {format: path relative to dataset root}.
- 2026-11-14 03:21 — Vision: Yytsi ResNet34-UNet (MIT) is the segmenter; CubiCasa official (CC BY-NC) is an internal fixtures baseline only; final detector = permissive RT-DETR fine-tuned on CubiCasa5K SVG boxes (V-07) — licence + coverage.
- 2026-11-14 03:26 — OCR = rapidocr-onnxruntime (Apache-2.0, runs in the Linux deploy image) over macOS Vision; added onnx for V-08.
- 2026-11-14 03:28 — Shared dev servers started by LEAD with `make dev` (logs/dev.log): API :8000, web :5173. Workers must not start their own copies.
- 2026-11-14 03:31 — Deployed API serves a baked-in demo subset of artifacts (demo docs only, publishable only, target < 150 MB) copied into the image at build time; Cloudinary replaces it if CLOUDINARY_URL arrives — Aiven Runtime builds from git and artifacts/ is not in git; no object storage key yet.
- 2026-11-14 03:31 — Aiven Runtime app goes in aws-eu-central-1 (do-fra has no Runtime plans), plan startup-10-256; DB stays hologram-pg in do-fra over TLS. /ws on Runtime is untested: test right after first deploy; fallback is client polling.
- 2026-11-14 03:31 — SERVER may edit engine/models/providers.py and the tts section of models.yaml to add an ElevenLabs adapter for S-08 (ENGINE is busy on solvers; LEAD-authorised cross-folder change).
- 2026-11-14 03:33 — I-04 starts before W-11: the native bridge handler and the /ws scene.highlight listener don't need the web button; done test uses a test bridge message.
- 2026-11-14 03:37 — T-04's '13 highlighted items' depends on vision accuracy (VISION's colorful-11397 plan map has 12 windows today). T-04 passes when every answer item that exists in the extruded scene is highlighted with matching labels; the literal 13 is re-checked when the plan map reaches 13 (tracked in V-11/E-19).
- 2026-11-14 03:49 — 3D and AR open in a cutaway view by default (roof and storeys above the answer's storey hidden, "Show roof" toggle). Rows T-11, I-10 added — Ash: roofs hide the answer items.
- 2026-11-14 03:51 — Deleted data/full/junction-dataset.zip (9.8 GB) after the unzip was verified (127,044 questions) — disk fell from 129 to 80 GB during the full batch; the zip is re-downloadable from the public URL.
- 2026-11-14 03:51 — VISION next = V-09 (geometry rules + model check of low-confidence items) before V-10 — windows (0.30) and doors (0.37) are the weakest cells and the demo's first question is a window count.
- 2026-11-14 03:54 — Fine-tuning keeps the strict rule: no drawing referenced by ANY questions.jsonl (preview or full) is used for training or tuning. The full set references 4,788 of 5,000 CubiCasa5K drawings, so only ~212 CubiCasa drawings are clean. Training data = those ~212 + permissively/NC-licensed external floor-plan datasets with no overlap (searched and recorded in docs/MODELS.md, e.g. FloorPlanCAD, ROBIN, R2V-style sets; licence checked) + synthetic plans rendered from non-question DXF/IFC sources with exact labels + heavy augmentation. Evaluate before/after on held-out only. Fine-tune gains may be modest; that is reported honestly — Honesty rules (section 4) and section 8 rule 1–2.
- Pretrained models (CubiCasa official, Yytsi UNet) already saw CubiCasa5K train drawings: allowed by section 8.3; VISION reports per official split (unseen 0.542 vs train 0.516: no inflation visible).
- 2026-11-14 03:55 — E-14 (rule library) goes to SERVER, editing only engine/rules/ — SERVER would idle until E-04; ENGINE doesn't touch engine/rules/.
- 2026-11-14 03:59 — Added W-18 (Stoa 1:1 fidelity, pixel-diffed against the 45 reference phase frames) as WEB's next row after W-07, and X-06 (LEAD-run live e2e demo test, no stub, after every relevant commit) — Ash: "looks and feels exactly like the Stoa flow, 1-1, then our features", and "test it live e2e".
- 2026-11-14 03:59 — Ash authorised up to $500 tonight for testing. Consequences: bench on sample1000.full and the full set may run more often than "4 full benches" when it measures a real change; X-07 stress/variety row added (300+ dataset questions, paraphrases, edge inputs, uploads of each format, concurrency, live sync); model comparison (E-10) uses wider sweeps. Every spend still goes through the model layer and caps.
- 2026-11-14 04:05 — Text/other questions abstain in engine.answer until E-08/E-09 build the model-written path; ENGINE does E-05 bench first, then E-08/E-09.
- 2026-11-14 04:07 — V-09 free pass (merge + conf<0.7 cut for door/window/toilet) is the default: held-out window 0.299→0.320, door 0.369→0.443, toilet 0.725→0.817, no kind worse. colorful-11397 itself went 12→11 windows (truth 13): demo docs will be picked by X-03 from test results, not assumed.
- 2026-11-14 04:17 — Added scene-command feature (E-20, S-10, T-12, I-14, W-19): 'show me all the windows' → tagged W1..Wn; 'remove window W7' → hidden live in 3D/AR/2D via /ws scene.edit; edits are a per-chat layer, never changing source data — Ash's idea.
