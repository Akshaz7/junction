# WEB4 (Codex) — current row

ROW: W-36 Skills, Automations (routines), Findings: every action works end to end
Ash: "make sure every single feature in the website works, like the skills, the routines, all of that".
For web/src/components/{skills-screen,automations-screen,findings-screen,library-screen,overview-screen}.tsx:
1. List every button/action and the API call it makes (web/src/lib/api.ts, docs/API.md). Check each server route exists in server/*.py with the same path and shape (read the code; note any mismatch).
2. Fix web-side mismatches (wrong path, wrong field names, missing loading/error state, no result shown after Run). Every Run/Create/Delete shows its result or a clear error with Retry; nothing silently does nothing.
3. Any action whose server route does not exist: remove the button and write NEEDS: <route> for LEAD.
4. A vitest per action with a mocked fetch asserting the exact request (method, path, body) and that the result renders.
Write the list (action → route → status) in this file.
Allowed: those five components + css + tests, web/src/lib/api.ts (+test), this file.
Done test: cd web && npx tsc --noEmit && npx vitest run (0 failures).
Never commit. Write one line at the end: RESULT: ...

ADDED by LEAD (QA-LIVE round 2, same row): the Findings, Skills and Automations drawing dropdowns list only ~14 colorful-* CubiCasa drawings; AC20 (ifc_bench__ac20-arc) and the other docs with data are missing, so Findings cannot run on the demo building. List every doc the checks can run on (IFC first, AC20 at the top), with a search box if the list is long.

W-36 action → route → status (WEB4):

| Screen / action | Request or local action | Status |
|---|---|---|
| All drawing lists | App's `GET /api/docs` → `{sources:[{docs:Document[]}]}`; flattened without page-count/kind filtering | Verified `server/docs_routes.py`; every supplied doc remains selectable, AC20 first, other IFCs next. Local API returned 796 docs including AC20. |
| Skills: Refresh / Retry list | `GET /api/skills` → `{skills:Skill[]}` | Verified `server/skills_routes.py`; loading, error + Retry, list rendered. |
| Skills: Save skill / Retry save | `POST /api/skills` `{name,prompt}` (trimmed) → 201 Skill | Verified; saved card and confirmation rendered, form cleared only on success. |
| Skills: choose drawing / search | Local selection and title/ID/kind/source search; no request | All docs retained; search shown for >20 docs; current selection stays visible. |
| Skills: Run skill / Retry run | `POST /api/skills/{id}/run` `{doc_ids:[selectedId]}` → `{answer}` | Verified; progress, answer, error + Retry. |
| Skills: Delete / Retry delete | `DELETE /api/skills/{id}` → 204 | Verified; removed card and confirmation. Built-in skills have no Delete. |
| Skills: answer citation / Close | Local citation opens/closes shared DocumentViewer | Verified screen wiring; embedded viewer's image/evidence requests remain covered by its existing suites. |
| Composer SkillPicker: choose / Retry skills | `GET /api/skills`; local `onPick(prompt)` | Verified; fills draft without running or submitting; load failure can retry. |
| Automations: Refresh / Retry list | `GET /api/automations` → `{automations:Automation[]}` | Verified `server/skills_routes.py`; loading, error + Retry, list rendered. |
| Automations: choose drawing / schedule / search | Local selections; 60 / 1440 / 10080 minutes | Selected values sent unchanged on Create; full drawing list and search as above. |
| Automations: Save / Retry save | `POST /api/automations` `{name,prompt,doc_ids:[selectedId],interval_minutes,enabled:true}` → 201 Automation | Verified; saved card, confirmation and report placeholder. |
| Automations: Run now / Retry run | `POST /api/automations/{id}/run` (no body) → Automation | Verified; latest report rendered. HTTP 200 with `last_report.ok:false` now shows failure + Retry. |
| Automations: Last report / Retry detail | `GET /api/automations/{id}` → Automation | Verified; selects latest saved report; detail failures retry the same read. |
| Automations: report load / Retry report | `GET /api/automations/{id}/report.md` → Markdown text | Verified; dedicated error state replaces stuck Loading; Retry reloads only the report. |
| Automations: Export .md | Local Markdown Blob download, sanitized filename; no new request | Verified download and MIME type; disabled until report content is available. |
| Automations: Delete / Retry delete | `DELETE /api/automations/{id}` → 204 | Verified; removed card, confirmation, selected report closed. |
| Findings: choose drawing / initial read / Retry list | `GET /api/findings?doc_id={selectedId}` → `{findings:Finding[]}` | Verified `server/findings_routes.py`; load/error/retry; no document leaves no loading indicator. |
| Findings: Run checks / Retry checks | `POST /api/findings/run` `{doc_id}` → `{status,findings}` | Verified; saved findings and completion / empty / no_checks result rendered. |
| Findings: advisor after checks / Retry advice | `POST /api/advise` `{doc_id}` → `{cards}` | Verified `server/advise_routes.py`; complete sources rendered; retry advice preserves successful findings without rerunning checks. |
| Findings: open finding / Show advisor items | `GET /api/docs/{doc_id}/planmap/{page}` for each page, then local evidence viewer | Verified `server/files_routes.py`; exact item IDs forwarded. IFCs without page boxes use the existing VisualisePanel scene path. |
| Findings: Close evidence | Local viewer dismissal | Verified. |
| Findings: Read source / Documents | Source's HTTP(S) URL / `#/data` | Verified safe source link and document navigation. |
| Library: Skills / Automations tabs | Mount corresponding screen → `GET /api/skills` / `GET /api/automations` | Verified matching list and tab content. |
| Library: Upload (no drawings) | Local navigation `#/data?upload=1` | Verified; automation creation disabled until a document exists. |
| Overview: changes section / Retry | `GET /api/changes` → `{changes}` | Verified `server/files_routes.py`; rendered changes and independent retry. |
| Overview: findings section / Retry | `GET /api/findings` → `{findings}` | Verified; sourced findings, severity counts, independent retry. |
| Overview: latest answers / Retry | `GET /api/chats` → `{chats}`, then `GET /api/chats/{id}` → chat with messages | Verified `server/chats_routes.py`; answer previews, costs and saved-chat links; list failure retries. |
| Overview: accuracy / Retry live results | `GET /api/bench/latest` → `{file,data}` | Verified `server/files_routes.py`; metrics rendered; recorded fallback now labelled with Retry live results. |
| Overview: Draft claim | `POST /api/chats` `{doc_ids:[],title:"Draft claim"}`, then `POST /api/chats/{id}/messages` `{content:<claim prompt>,doc_ids:[]}` | Verified exact prompt, request bodies and SSE answer; answer rendered and saved chat opened. |
| Overview: Meeting prep | Same two routes, title "Meeting prep", exact meeting prompt | Verified independently. |
| Overview: Plan work phase | Same two routes, title "Plan work phase", exact work-phase prompt | Verified independently. |
| Overview: Review contract | Same two routes, title "Review contract", exact contract prompt | Verified independently. |
| Overview: Retry starter | Retry failed Create, or reuse created chat and retry messages POST | Verified; successful Create is not duplicated; failure retains Open saved chat link. |
| Overview: view changes / latest answers / saved chat / accuracy | `#/changes`, `#/chat`, `#/chat?chat={id}`, `#/accuracy` | Verified navigation targets. |
| Overview: finding source disclosure | Local details/summary expansion | Source title and quote rendered. |

No missing server routes or request-field mismatches found. Changes address feedback/recovery and drawing ordering/search. No backend or contract edits needed for the local API. Deployed dropdown availability still depends on that deployment returning its artifact-backed documents from GET /api/docs; the web does not invent missing document records.

Files for LEAD to stage: web/src/components/skills-screen.tsx, web/src/components/skills-screen.css, web/src/components/automations-screen.tsx, web/src/components/findings-screen.tsx, web/src/components/overview-screen.tsx, web/src/components/workspace-actions.test.tsx, handoff/WEB4.md.
Validation: `cd web && npx tsc --noEmit && npx vitest run` passed (59 files, 373 tests; includes 48 new mocked-fetch screen tests). No Playwright or heavy jobs run. No commits.
RESULT: W-36 passed — all scoped actions mapped to real routes; create/run/delete feedback and Retry added, failed reports handled, AC20/IFC-first searchable drawing lists preserved; TypeScript and all 373 Vitest tests pass.
