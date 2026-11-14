# MORNING: report for Ash

_Last updated: Sat 14 Nov 09:15 EET (run 1). See TASKS.md for every row._

## 1. What works
| Demo step (MASTER_PROMPT §12) | Status |
|---|---|
| 1. Stoa-style web app | yes: Stoa 1:1 pass (W-18): all 18 desktop screens and 18/20 phone screens within 1.5 % pixel difference of the reference frames, 2 phone screens at 1.66/1.88 % with no unexplained area (results/fidelity/report.json). Overview, Accuracy dashboard, voice buttons done. Preview: http://localhost:4173 |
| 2. Count question on raster plan, status lines, bold answer, chips | yes on the real engine: "How many windows are there?" on colorful-11397 → 11 windows, 11 numbered evidence items, $0, 2 ms (S-04 done test still being finished) |
| 3. Chip opens drawing with numbered boxes; cost chip | yes (W-06, W-07, W-18): Stoa-style viewer header + toolbar, numbered boxes, cost chip, speaker button for the spoken answer (W-14) |
| 4. "Visualise it" 3D with same items glowing | yes (T-00..T-07, T-11, T-12): roofs hidden by default; 2D↔3D linked clicks (T-03); "show me all the windows" → W1..Wn, "remove W3" fades out live in 2D and 3D on every open device within 0.8 s (W-19, measured on the Mac GPU), and later answers count only what is visible ("how many windows" → 205 after removing W7, E-20); largest model 99.6 MB loads in 1.2 s, 60 fps on the Mac (results/viewer3d_perf.json). Click any tag on a drawing → Item details panel with IFC properties and the other places it appears (W-13). |
| 5. iPhone: same chat, "Show on table" AR | yes in the simulator: the web "Show on table" opens native AR with the same doc and items (I-04), AR keeps the web page and draft across the round-trip (I-15), scene commands W1../hide/restore (I-14), advisor cards (I-09). Device install waits for Ash (I-05). |
| 6. IFC fire exit on level 2, camera flies, 1:1 walk | partly: fire-exit rule check works on AC20 (findings API + red/amber pins in 3D, T-09); browser walk mode (T-10) and AR walk (I-06) done; exit-route answer is model inference and labelled so (DEMO.md) |
| 7. Dashboard: accuracy by source/type, before/after fine-tune, cost/answer | yes (W-08) on the real bench. First real bench: 25.7 % overall on sample200 (answered 33.3 %), counts 32 %, areas mostly abstain, $0 for numeric answers (results/bench/sample200-r2.json). Improving this is the main work now (E-10/E-19, vision fine-tune V-06/V-07). |
| 8. Edit in 3D → sourced advisor card | partly: 3D edit mode (remove/move/material) sends advisor requests and renders sourced cards (T-08); engine advisor rules in progress (E-16). Building-rule sources are watched live: 2 Context.dev monitors (results/watch/monitors.json) feed a 'rule source changed' entry and rerun the checks (E-17; the webhook attaches once the backend is deployed) |

## 2. Numbers (each from a results/ file)
- First full bench (results/bench/full_1.json): all 63,307 numeric questions, 56.7 % (answered 62.7 %; area answered 91.0 %), total cost $0.05; text questions subsample 42.1 % (model-judged). Model comparison in results/model_compare.json: Runware gemini-3.1-flash-lite is the cheapest model within reach of the best for routing and text judging; Gemini/Claude direct not run (keys missing).
- Answer accuracy (results/bench/sample200-r10.json, docs/ACCURACY.md): 66.3 % on sample200 (counts 63.0 %, areas 79.5 %), from 25.7 % at the start of the night; numeric answers cost $0. IFC text questions went from 37.5 % to 72.7 % judged after E-09 (results/bench/e09_text.json).
- Stress (results/stress/stress-r2.json, after the overnight CubiCasa plan-map batch): 421 cases, 0 crashes, 0 server errors, 0 invalid answers, 0 prompt-injection leaks, p95 0.85 s, $0. Dataset group 153/300 (r1: 60/300), accuracy 50.2 % (r1: 18.6 %); edge cases 55/55, paraphrases 60/66.
- 3D performance (results/viewer3d_perf.json): largest model 99.6 MB / 5.4 M triangles loads in 1.2 s, 60 fps on the Mac.
- Stoa look (results/fidelity/report.json): all desktop screens and nearly all phone screens within 1.5–2 % of the reference frames.
- Router (question parser): 97.4% on 420 unique held-out questions with rules only, $0 per question; Nemotron fallback alone 95.0% at $0.0000025/question (`results/router_cost.json`). kind/scope labels were written by ENGINE: treat 97.4% as an upper bound.
- Vision on the 4 cubicasa fixtures (`results/vision/timing.json`, counts in TASKS notes): colorful-11397 windows 12/13, toilets 2/2, sinks 3/3, showers+bathtubs 0/3. Full per-kind accuracy comes with V-04 (`results/vision/baseline.json`).
- Spend so far (`results/costs.jsonl`): Runware $0.017, ElevenLabs $0.010, NVIDIA $0 (free tier). Modal $0.

## 3. Deployed URLs
- Web: https://hologram-khaki.vercel.app (Connected workspace, real answers; checked live 09:15: 12 windows on colorful-11397 with 12 citations, 0 page errors).
- API: https://hologram-api.vercel.app (Vercel Python function, same FastAPI app as the container) on Aiven PostgreSQL hologram-pg (EU). Health ok, rate limit 30/min/IP active. Demo docs baked in (deploy/demo_artifacts).
- Not yet: live sync across devices (/ws) — Vercel can't hold WebSockets. That moves to Aiven Runtime once the Aiven GitHub App is installed (deploy/README.md); the container image is verified.

## 4. Rows blocked
- V-06, V-07, V-08 (vision fine-tunes): the Modal workspace is paused (every call: "Workspace … is paused"). Un-pause it in the Modal dashboard; scripts are ready (results/vision/seg_finetuned.json, det_finetuned.json).
- I-05 (install on iPhone): blocked-human, by design (Ash plugs in the phone in the morning).
- ifc_models__resbim-388-model: a 2.5 KB stub IFC, skipped (not a row).

## 5. Keys that failed
None now. OK: NVIDIA, Runware, HF, ElevenLabs, Modal, Aiven. Missing: GEMINI_API_KEY, ANTHROPIC_API_KEY (both covered by Runware for now), CLOUDINARY_URL, Google Drive credentials.

## 6. What Ash must do by hand next
- iPhone: at 04:20 `xcrun devicectl` already listed "Akshat's iPhone … available (paired)" (reachable over Wi-Fi). Unlock it, make sure Developer Mode is on, then run `bash ios/scripts/install_on_device.sh` (one command; see ios/README.md). Nothing was installed overnight.
- Fill missing keys in `.env`.
- Saturday morning: plug in the iPhone (unlocked, trusted, Developer Mode on), (APPLE_TEAM_ID 472PHZCF99 already in .env), then follow the I-05 install steps below; test AR on a table; run the demo script once.
- Aiven: install the Aiven GitHub App for repo Akshaz7/junction in the Aiven console (Integrations / GitHub) so the Runtime app can build from the repo (needed for deploy, S-05).
- Aiven: a second PostgreSQL service `pg-39dadbc6` (developer-1, do-fra) exists next to ours (`hologram-pg`). If you didn't mean to create it, power it off to save credit.
- Logins still missing (see STATE.md).
- Before Sunday 10:00: record the 2-minute video, fill the submission form, switch DRAFT → FINAL, join peer review 10:30–14:00.


## 7. Proposed plan for the next run
Run 1 status: every row is done (98) or blocked with a reason. Deployed on Vercel (S-05 done); for live sync, install the Aiven GitHub App so the backend can move to Aiven Runtime, I-05 iPhone install, V-06/V-07/V-08 (Modal workspace paused), D-13/D-14/V-11/E-19 (missing keys: Gemini, Anthropic, Cloudinary, Google Drive). Next run: deploy as soon as the GitHub App is in, then fine-tunes on Modal, then the improve loop on the weakest cells (length/volume abstain on all questions; ifc_models abstains on 80 %).

## 8. Known weak spots to avoid in the live demo
- Bathtub/shower counts on raster plans (0/3 on colorful-11397).
- Raster areas use a door-width scale estimate on most cubicasa plans: low confidence.
- localhost:5173 can be blank mid-edit; demo from the stable build (localhost:4173) or the deployed URL.
