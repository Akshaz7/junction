# 3D viewer

This folder belongs to the 3D worker. WEB leaves the implementation to that worker.

`Viewer3D` mounts and disposes the three.js viewer, with orbit controls, a storey
dropdown, loading/error messages, and a picked-item details card:

```tsx
import { Viewer3D } from './viewer3d';

<Viewer3D
  doc_id={docId}
  storey={null}
  onPick={(item_id) => console.log(item_id)}
/>
```

Give its parent a height (the component has a 420px minimum). `storey` defaults to
all storeys; changes to the prop update the filter, and the dropdown can also be
used directly. Clicks report the contract item ID; dragging only orbits.
Changing `sceneUrl` disposes the previous viewer and ignores stale scene loads.
`doc_id` loads `/api/docs/{doc_id}/scene` and resolves geometry through
`/api/docs/{doc_id}/files/scene.glb`, ignoring filesystem paths in the manifest.
Existing `sceneUrl` API callers get the same resolution. Offline URLs keep their
relative GLB assets.

Clicking an item opens its name, kind, storey and known properties. For API
scenes the viewer also requests `/api/docs/{doc_id}/files/elements.json` and
joins the pipeline's `elements` array by exact `item_id`. Missing metadata falls
back to the item ID and scene kind/storey; quantities are never guessed from
bounding boxes. Available IFC class/type, width/height/length/area/volume,
material, fire rating and external flag appear in the card. Its close button,
Escape, an empty canvas click, a storey change or a document change dismiss it.

Pass `highlightItemIds` and `highlightOptions` to highlight answer evidence:

```tsx
<Viewer3D
  sceneUrl={`/api/docs/${docId}/scene`}
  highlightItemIds={answer.evidence.scene.highlight_item_ids}
  highlightOptions={{
    labels: Object.fromEntries(answer.evidence.boxes.map(box => [box.item_id, box.label])),
    cameraTargetItemId: answer.evidence.scene.camera_target_item_id ?? undefined,
  }}
/>
```

The imperative API is available from `createViewer(canvas)` or `onReady(viewer)`:
`viewer.highlight(item_ids, { labels?, cameraTargetItemId? })`,
`viewer.clearHighlight()`, and `viewer.getHighlightState()`.
Missing IDs are ignored; labels default to sequential numbers when omitted.
An empty selection clears the highlight. State reports resolved item IDs,
the number of other resolved items (including hidden storeys), and label strings.
Highlighting preserves the storey filter. Keep React option references stable
when possible so unrelated renders do not restart the camera flight.

Selected materials emit the runtime `--mode-accent` token (fallback `#166ed1`);
other geometry is faded and desaturated. Each mesh receives separate material
clones. Clearing, replacing a scene, or disposing restores original material
references and disposes only the clones. CSS2D labels sit above geometry bounds
and follow storey visibility. The camera eases to the target item, or the union
of selected items, in 600 ms. Orbit input cancels the flight. Clearing leaves
the camera at its current position.

The LEAD should mount the exported `ViewerTestPage` at `/#/viewer-test` in the app
router. It loads the real DigitalHub fixture served at
`/fixtures/digital_hub/scene.json`. The public assets are relative symlinks to the
existing unit fixture, with the upstream MIT notice alongside them.
It also provides “Highlight 3 random items” and “Clear highlight” controls.
The Document dropdown switches between the offline fixture and the real
`ifc_bench__ac20-arc` API document. Only this test page exposes `window.viewer3dTest`
for browser helpers to position the camera and project a known item's bbox.

Validation: `npx vitest run src/viewer3d` and `npx tsc --noEmit` from `web/`.
The LEAD runs `scripts/heavy.sh` with
`npx playwright test e2e/viewer3d.spec.ts` from `web/` outside the worker sandbox.
The browser test uses SwiftShader and reads pixels during an animation frame;
more than 1% of the canvas must differ from the background. It also filters a
storey, clicks a rendered surface, and checks the returned ID against the fixture.
The LEAD also runs `npx playwright test e2e/viewer3d-highlight.spec.ts` through
`scripts/heavy.sh`. It saves before/after canvas screenshots, checks they differ,
checks citation labels, and clears the selection.
`e2e/viewer3d-identify.spec.ts` switches to AC20, projects a known Keller door's
bbox centre, clicks it, checks identity/storey, and dismisses the card. Its camera
sits within the opening so enclosing IFC space surfaces cannot intercept the
door click. The optional elements endpoint enriches the assertion when available.
