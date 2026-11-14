# STATE

## Paths (confirmed in PHASE A, 2026-11-14 02:40 EET)
| Thing | Location | Status |
|---|---|---|
| Repo | /Users/akshatthapa/Workspace/junction (origin github.com/Akshaz7/junction, public) | OK |
| Preview dataset | data/junction-dataset-preview/ (questions.jsonl: 7,990 lines; files under data/junction-dataset-preview/data/<source>/) | OK |
| Spike output | out/ (4 GLB + elements.json + logs), scripts/extract_elements.py, scripts/validate_glb.py | OK |
| IfcConvert | tools/IfcConvert 0.8.4-e8eb5e4 | OK |
| Stoa reference pack | refs/stoa-hero/ (copied from ~/.aside/.../artifacts/stoa-hero, 403 MB, git-ignored) | OK |
| Scraped Stoa site text | refs/stoabuild-full-text.md | MISSING: not on the Mac. Fallback for the voice guide: refs/stoa-hero/02-phase-map.md + source/tour-copy-strings.en.js (style only) |
| Keys | .env (git-ignored) | Runware only at 02:42 |

## Tool versions
git 2.54.0, uv 0.12.17 (Python 3.12.14 managed by uv; repo .venv is 3.12), node v26.13.0, Docker 28.4.0, Xcode 27.2, xcodegen 2.44.1, gh 2.86.0, vercel 50.44.0, modal 1.6.4 (installed in PHASE A), codex 0.167.2, avn 4.19.0 (installed in PHASE A). Machine: Apple M4 Pro, 24 GB, macOS 26.6.2, 147 GB free.

## Preflight (02:43)
Not OK: refs/stoabuild-full-text.md MISSING, modal login MISSING, aiven login MISSING, iPhone MISSING. All other paths, tools and logins OK (gh, vercel, codex, codex exec unattended). Keys: RUNWARE_API_KEY OK, the rest MISSING.

## Hourly log
- 2026-11-14 02:45 PHASE A complete. Waiting for /goal.
