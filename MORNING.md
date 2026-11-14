# MORNING: report for Ash

_Last updated: Sat 14 Nov 04:55 EET (run 1). Rows: 49 done, 10 doing, 43 todo, 4 waiting for a key, 1 needs Ash._

## 1. What works
| Demo step (MASTER_PROMPT §12) | Status |
|---|---|
| 1. Stoa-style web app | partly: shell, chat screen and Data screen done (W-01, W-04, W-05); see http://localhost:4173 |
| 2. Count question on raster plan, status lines, bold answer, chips | yes on the real engine: "How many windows are there?" on colorful-11397 → 11 windows, 11 numbered evidence items, $0, 2 ms (S-04 done test still being finished) |
| 3. Chip opens drawing with numbered boxes; cost chip | yes (W-06, W-07). Stoa 1:1 look: in progress (W-18 attempt 3; pixel diff now 0.1–8 % per screen, was meaningless before) |
| 4. "Visualise it" 3D with same items glowing | yes (T-00..T-02, T-04..T-06, T-11): roofs hidden by default, live highlight sync between devices. 2D↔3D linked clicks: code ready (T-03), wiring after W-18. "Show me all the windows" / "remove W3" in 3D: T-12 in progress |
| 5. iPhone: same chat, "Show on table" AR | partly: iOS shell, AR screen, highlights, walk mode, tap-identify done in simulator (I-01..I-03, I-06, I-08); USDZ for 130 scenes (D-10); scene commands W1../hide/restore in AR done (I-14); advisor cards attempt 2 (I-09); bridge waits for W-11 (I-04); device install needs Ash |
| 6. IFC fire exit on level 2, camera flies, 1:1 walk | no (E-13 not started; walk mode I-06 done) |
| 7. Dashboard: accuracy by source/type, before/after fine-tune, cost/answer | no (bench E-05, vision eval V-04 in progress) |
| 8. Edit in 3D → sourced advisor card | no (tier 3) |

## 2. Numbers (each from a results/ file)
- Router (question parser): 97.4% on 420 unique held-out questions with rules only, $0 per question; Nemotron fallback alone 95.0% at $0.0000025/question (`results/router_cost.json`). kind/scope labels were written by ENGINE: treat 97.4% as an upper bound.
- Vision on the 4 cubicasa fixtures (`results/vision/timing.json`, counts in TASKS notes): colorful-11397 windows 12/13, toilets 2/2, sinks 3/3, showers+bathtubs 0/3. Full per-kind accuracy comes with V-04 (`results/vision/baseline.json`).
- Spend so far (`results/costs.jsonl`): Runware $0.017, ElevenLabs $0.010, NVIDIA $0 (free tier). Modal $0.

## 3. Deployed URLs
None yet. Aiven Postgres `hologram-pg` is running (EU, do-fra) and seeded. App deploy waits for the Aiven GitHub App (below) and the tier-1 web rows.

## 4. Rows blocked
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
Finish tier 1 (E-04 → S-04 real answers, W-06 viewer, T-04 Visualise it, E-05 bench, W-07, W-08 dashboard, X-01 README), then deploy (S-05) once the GitHub App is installed.

## 8. Known weak spots to avoid in the live demo
- Bathtub/shower counts on raster plans (0/3 on colorful-11397).
- Raster areas use a door-width scale estimate on most cubicasa plans: low confidence.
- localhost:5173 can be blank mid-edit; demo from the stable build (localhost:4173) or the deployed URL.
