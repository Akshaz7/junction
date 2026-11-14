# Handoff: WEB (Codex worker)

Row ID: W-19 + W-12 + X-06 bugs (attempt 2)
LEAD full run 06:18 on your finished tree (results/e2e/full-0618/run.log; fidelity report + diffs in results/fidelity/). 64 passed, 19 failed. Some failures were caused by a stress run hitting the same API (overview ordering, 2.05 s sync) or by tag labels in 3D (3D worker fixing). Yours:
1. fidelity chat phases (desktop-7..11, phone-9..14): `expect(page).toHaveURL(/#\/chat$/)` now receives "#/chat?chat=fidelity-generated-chat" because new chats update the URL (bug fix 4, correct). Update the harness expectation to accept the ?chat= query. Then check whether those phases' pixels still pass.
2. phone-3-2950: 6.668 % mismatch, 1 unexplained region — a real visual regression from this round (Data screen on phone; probably the tab-bar/preview fix). See results/fidelity/diffs/phone-3-2950.png and fix so phone-3 is back ≤ 2 % with 0 unexplained regions.
3. overview.spec.ts:13 assumes its new chat is the first in "Latest answers"; other clients can create chats at the same time. Find the chat link by its id instead of `.first()`.
4. scene-commands.spec.ts:57 remote edit arrived in 2049 ms (limit 2000) — measured during the stress run; LEAD will rerun without load. If the client adds avoidable delay (debounce, refetch before apply), remove it.
Do not edit demo-flow.spec.ts (LEAD's live test).
Done test (LEAD runs): full web suite incl. demo-flow, scene-commands, changes, fidelity → pass.
Last failed attempt (if any): see above.

---
<!-- Worker appends RESULT: or NEEDS: lines below. -->
NEEDS: W-19 + W-12 + X-06 attempt 2 ready for LEAD browser verification: fidelity accepts ?chat=; overview rows/click use chat IDs; phone previews open fullscreen with the zoom pill exposed, while retained previews dock above tabs on return from Chat (preserves demo-flow tab hit testing); data.spec covers both states. Scene socket callbacks dispatch immediately with no debounce/refetch dependency, so unchanged. Build and 184 unit tests pass; targeted fidelity launch fails before capture with Chromium MachPortRendezvous Permission denied (1100), so pixel thresholds and the full suite remain unverified. Rerun full web suite without stress; local blocked capture overwrote results/fidelity/report.json with a partial error report. demo-flow.spec.ts untouched; no commits.
