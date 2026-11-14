# MORNING — report for Ash

_Last updated: (not yet; PHASE A only)_

## 1. What works
| Demo step (MASTER_PROMPT §12) | Status |
|---|---|
| 1. Stoa-style web app | no |
| 2. Count question on raster plan, status lines, bold answer, chips | no |
| 3. Chip opens drawing with numbered boxes; cost chip | no |
| 4. "Visualise it" 3D with same items glowing | no |
| 5. iPhone: same chat, "Show on table" AR | no |
| 6. IFC fire exit on level 2, camera flies, 1:1 walk | no |
| 7. Dashboard: accuracy by source/type, before/after fine-tune, cost/answer | no |
| 8. Edit in 3D → sourced advisor card | no |

## 2. Numbers
(Only from `results/` files. None yet.)

## 3. Deployed URLs
None yet.

## 4. Rows blocked

## 5. Keys that failed

## 6. What Ash must do by hand next
- Fill missing keys in `.env`.
- Saturday morning: plug in the iPhone (unlocked, trusted, Developer Mode on), (APPLE_TEAM_ID 472PHZCF99 already in .env), then follow the I-05 install steps below; test AR on a table; run the demo script once.
- Aiven: install the Aiven GitHub App for repo Akshaz7/junction in the Aiven console (Integrations / GitHub) so the Runtime app can build from the repo (needed for deploy, S-05).
- Aiven: a second PostgreSQL service `pg-39dadbc6` (developer-1, do-fra) exists next to ours (`hologram-pg`). If you didn't mean to create it, power it off to save credit.
- Logins still missing (see STATE.md).
- Before Sunday 10:00: record the 2-minute video, fill the submission form, switch DRAFT → FINAL, join peer review 10:30–14:00.

## 7. Proposed plan for the next run

## 8. Known weak spots to avoid in the live demo
