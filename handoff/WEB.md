# Handoff: WEB (Codex worker)

Row ID: W-04 (attempt 2)
Task: App shell following the reference pack: sidebar, layout, type, colours, controls. Study `refs/stoa-hero/00-hero-reference.png`, `01-desktop-contact-sheet.png`, `01-phone-contact-sheet.png`, `01-design-tokens-and-shell.md`, `03-build-guide.md` (component map, Button variants, type scale, spacing) and a few frames in `refs/stoa-hero/desktop-frames/`. Build: left sidebar with our own wordmark "Hologram" (text wordmark, no Stoa logo), nav items Overview, Chat, Changes, Data, Accuracy, Skills, Automations, a project switcher showing "Demo workspace", main content area with a router (react-router or a tiny hash router) and placeholder pages for each nav item. Reusable components in `web/src/components/ui/` (Button with the variants from the build guide, Card, Badge, Chip, Input, Tooltip) using the CSS variables from `web/src/styles/tokens.css`. Fonts as named in the build guide (Google Fonts only). The UI copy follows `refs/stoabuild-full-text.md` in tone. Never copy code from `refs/stoa-hero/source/`.
Playwright cannot launch Chrome inside your sandbox: write the e2e test, make sure it type-checks, and the LEAD runs it.
Input files: as above; CONTRACT.md 5.8
Done test (LEAD runs): `cd web && npm run build && npx playwright test e2e/shell.spec.ts` — the test finds all nav items and checks 10 CSS variables on :root against `refs/stoa-hero/theme-tokens.css` values.
Last failed attempt (if any): attempt 1 — LEAD ran `npx playwright test e2e/shell.spec.ts`: 3 passed, 1 failed:
  e2e/shell.spec.ts:42 "phone navigation keeps all pages reachable without horizontal overflow"
  Error: expect(locator).toHaveAttribute('aria-current','page') — element not found: getByRole('navigation', { name: 'Mobile navigation' }).getByRole('link', { name: 'Accuracy' })
At phone width the mobile navigation has no "Accuracy" link. Per the plan (W-11) the phone bottom tabs are Overview, Chat, Changes, Data, More — put Accuracy, Skills, Automations under "More" and make the test follow that (open More, then the link), or include them in the mobile nav. Keep all pages reachable on phone with no horizontal overflow. The LEAD will re-run all 4 tests.

---
<!-- Worker appends RESULT: or NEEDS: lines below. -->
RESULT: W-04 implemented seven hash routes, responsive Hologram sidebar/mobile navigation, Demo workspace selector, Google Fonts Inter, and Button/Card/Badge/Chip/Input/Tooltip; npm run build and npm test pass (9 tests), and all 4 shell Playwright tests are discovered and type-checked; browser execution remains with LEAD per handoff.
RESULT: W-04 attempt 2 corrected the phone Playwright flow to reopen More after navigation before checking Accuracy/Skills/Automations active links; checks route URLs, menu closure, and overflow on every page with More open and closed. npm run build passes (including e2e type-check); all 4 shell tests discovered via scripts/heavy.sh. LEAD must run browser tests per handoff.
