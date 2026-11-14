# Handoff: WEB2 (Codex, second WEB-scoped worker)

Row ID: W-13 (attempt 1) — Linked codes: tags on the drawing are clickable and open the related places and properties beside the plan.
API (SERVER is adding it now, shape fixed by LEAD): `GET /api/docs/{doc_id}/items/{item_id}` and `GET /api/docs/{doc_id}/tags/{tag}` → {item_id, kind, tag, name, storey, type_name, props (IFC properties dict), places: [{doc_id, page, bbox_px | null, storey}]}; 404 unknown. Until it exists, your unit tests use a fixture; the e2e is real-API only.
Allowed files this time: new web/src/components/item-panel.tsx (+ .css), web/src/lib/linked.ts (+ test), web/e2e/linked-codes.spec.ts, AND web/src/components/document-viewer.tsx (only to make evidence boxes/tags clickable and to mount the panel). WEB is editing chat-screen.tsx and App.tsx right now — do NOT touch those or anything else.
Do: in the drawing viewer, every numbered box and tag label is clickable (keyboard: Enter) → a side panel ("Item details") beside the plan shows kind, tag, name, storey, type, IFC properties (key/value list, long values wrap), and "Appears in" places (each opens that page with the box focused). Escape/close returns focus. Phone: bottom sheet. Stoa look; don't change the viewer's default layout when no item is selected (fidelity must stay green).
e2e (real API): on ifc_bench__ac20-arc, open a drawing/plan view that shows a door (an AC20 storey plan page if available via the API, otherwise the answer evidence for "What is the narrowest door width used here?"), click the door's box → panel shows its storey, type and at least one IFC property, equal to the API response for that item.
Done test (LEAD): `cd web && npx vitest run && npx playwright test e2e/linked-codes.spec.ts e2e/viewer.spec.ts e2e/fidelity.spec.ts` → pass.
Last failed attempt (if any): none

---
<!-- Worker appends RESULT: or NEEDS: lines below. -->
