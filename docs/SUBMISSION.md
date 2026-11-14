# Hologram — submission checklist and draft fields

Target: **Sunday 15 November 2026, 10:00 Finland time (EET)**. The project brief sets a **07:00 hard freeze**, **08:30 final report**, and requires a **two-minute video and source link** ([brief](MASTER_PROMPT.md)). Check the event form's current requirements before switching DRAFT to FINAL. This prepares the submission; it does not submit it.

## Links for the form

| Field | Value / check |
| --- | --- |
| Live app | [Hologram](https://hologram-khaki.vercel.app/) — fresh-browser question, citation, 3D and upload check. |
| Public source | [Akshaz7/junction](https://github.com/Akshaz7/junction) — confirm public access. `[PENDING: submitted commit SHA / permalink]`. |
| Two-minute video | `[PENDING: public or unlisted video URL]` — playable without login; keep local copy. |
| Physical AR clip | `[PENDING: iPhone clip URL and downloaded backup]` — placement, build-up, voice and laptop return; may be part of main video. |
| Final report | `[PENDING: final report URL / uploaded filename]` — appropriate export of [MORNING.md](../MORNING.md), checked for private operational details. |
| Demo instructions | [Exact clicks, timed takes and Plan B](DEMO.md). |
| Accuracy | [Report](ACCURACY.md), [sample200-r10 summary](../results/bench/sample200-r10.json), [rows](../results/bench/sample200-r10.rows.jsonl). `[PENDING: final selected run/permalink]`. |
| Licences / integrations | [MODELS.md](MODELS.md), [MIT licence](../LICENSE), [sponsor evidence](sponsors/README.md). |

The configured API target is Aiven Runtime ([rewrite](../web/vercel.json), latest [decisions](../DECISIONS.md)); Vercel Python API remains a fallback. Older deployment/sponsor notes describe earlier blockers. Verify actual health and laptop↔phone delivery before claiming deployment/live-sync acceptance. Never put keys or database connection strings in the form.

## Draft submission fields

**Project name:** Hologram

**Punchline:** Ask a blueprint. Check the proof. Put the building on your table.

**Pitch:** “We rebuilt Stoa's product in two days. Then we built the part that does not exist yet.”

**Description:** Hologram answers English questions about construction drawings and BIM models with inspectable evidence. It reads drawings into structured plan maps and uses code for supported counts and measurements; models handle questions needing interpretation. Answers link to numbered drawing regions and matching 3D items. The iOS app places the selected scene on a table in AR. The intended judging flow carries one conversation from laptop to phone, then returns a spoken AR question and its answer to the laptop. Judges can upload their own drawings and inspect the resulting evidence. Readiness depends on input format, processing and source quality; missing evidence and estimated scale remain explicit.

**Demo extension — include after physical rehearsal:** A 2D plan becomes a building on the table. “Show me the doors” brings targets into view with spinning, sequential highlights, and the voice turn appears in the shared laptop chat. `[PENDING: device recording of this sequence on the submitted build]`.

**Tech used:** React, TypeScript, Vite, Tailwind CSS, three.js; SwiftUI, RealityKit, ARKit; Python, FastAPI, asyncpg, PostgreSQL; IFC/DXF processing and drawing-reading models. Web: Vercel. Backend target: Aiven Runtime with Aiven PostgreSQL. Provider calls use `engine/models` `call()` with routing, caching and cost records. List only providers with execution evidence; configured adapters do not prove usage.

**Primary challenge:** Stoa — Make Blueprints Talk.

**Additional challenge candidates:** [Nemotron](sponsors/nemotron.md), [Runware](sponsors/runware.md), [ElevenLabs](sponsors/elevenlabs.md), [Aiven](sponsors/aiven.md), [Codex](sponsors/codex.md). Check event eligibility and execution evidence before selecting each. Reconcile Aiven's older “Runtime pending” note with current deployment evidence. Add Modal or other services only with a completed run/integration, not merely a key or script. Models accessed through Runware are not direct Google API usage without direct-provider records.

## Evidence for the four criteria

| Criterion | Show / link | Claim boundary |
| --- | --- | --- |
| Accuracy | Judge's question against original source; benchmark summary and rows. | Curated demo success is not benchmark accuracy; separate numeric and text scoring. |
| Visual verifiability | Citation → numbered 2D boxes → same 3D/AR items, source credits visible. | Verify document/IDs on uploads too; never silently substitute bundled scenes. |
| Creativity | Physical-iPhone plan build-up, voice target animation, laptop return. | Show complete sequence; unverified effects remain pending. |
| Low inference cost | Actual answer cost/trace, ingestion spend and model-call records. | $0 code answer does not mean free ingestion, voice or infrastructure. |

Recorded reference: [sample200-r10](../results/bench/sample200-r10.json), the run behind [ACCURACY.md](ACCURACY.md), has 200 questions, with 13 text questions reported separately; **124/187 numeric correct (66.3%)**, including 16 numeric abstentions as unsuccessful. Its recorded total model cost is **$0**. This is not the final engine's score. Do not merge text judging or router accuracy into numeric accuracy.

Fill from `results/` only:

- `[PENDING: final benchmark tag, evaluated set/split and sample size]`.
- `[PENDING: numeric accuracy including abstentions; answered accuracy and denominator]`.
- `[PENDING: text correct/partial/wrong/abstained/unjudged and judge method]`.
- `[PENDING: answer versus ingestion cost, cache/provider mix and latency scope]`.
- `[PENDING: matched fine-tuning comparison, if any; otherwise omit gain claim]`.
- `[PENDING: physical AR and bidirectional live-sync evidence]`.

Use [cost records](../results/costs.jsonl), [upload results](../results/upload_live.json), [curated candidates](../results/demo_candidates.json), and the selected benchmark summary/rows. Reconcile against the report. If evidence is absent, leave the internal field pending or omit the public claim.

## At the 07:00 freeze

- [ ] LEAD selects the submitted commit and deploys that build; DOCS does not commit/deploy.
- [ ] Open public app/repo without authentication. Check real document selection, fresh answer, citation proof, **Visualise it** and API health.
- [ ] Rehearse [the full flow](DEMO.md) on laptop and physical iPhone: same chat → **Show on table → Place model** → 2D build-up → “show me the doors” → spin/sequential highlights → voice turn on laptop. Record unsupported segments explicitly.
- [ ] Upload an unseen supported drawing; inspect stages, answer and evidence. Retain format and scale limitations.
- [ ] Prepare normal/offline AR_DEMO builds, downloaded video and backup questions. Ensure the main take opens the intended scene.

## By the 08:30 report

- [ ] Report what works, blockers, selected benchmark tag, scoring rules, failures and costs. Copy numbers only from corresponding `results/` files.
- [ ] Export the two-minute video using [the shot list](DEMO.md). Include actual evidence, 3D, physical AR and voice return; caption recorded footage and edited waits. Simulator footage is not physical AR proof.
- [ ] Retain source credits. Label every generated fixture or synthetic revision **generated for demo**; do not present it as a real project document.
- [ ] Check report/video for keys, `.env` content, database URLs, service-account files, private judge drawings and unapproved personal information.

## Before 10:00 — final handoff

- [ ] Fill name, punchline, description, team, eligible challenges, source, app, video, report and required attachments in the actual form.
- [ ] Resolve every `[PENDING: …]` copied into public fields, or remove the unsupported claim; keep remaining internal gaps explicit.
- [ ] Check video/report links without login; audio, table placement and laptop voice turn must be clear. Keep downloaded copies ready.
- [ ] Confirm repo MIT licence and separate model/dataset terms in [MODELS.md](MODELS.md). Hosted model access does not make weights or drawings MIT.
- [ ] Exclude `publishable: false` scenes: Duplex / Dental Clinic (CC BY-ND) and hitos (GPL data). Respect CubiCasa5K CC BY-NC-SA and all source credits. No AGPL/GPL dependencies, Stoa logo/drawings or copied reference source code.
- [ ] Verify submitted assets omit keys, local datasets/reference packs, weights and prohibited artifacts. Check drawing permissions, including permission before publishing a judge's upload.
- [ ] Switch the actual form from DRAFT to **FINAL / submit** before 10:00 EET. Save confirmation: `[PENDING: receipt / submission URL]`.
- [ ] Keep charged devices, downloaded video and backups ready for judging; the brief schedules peer review for 10:30–14:00.
