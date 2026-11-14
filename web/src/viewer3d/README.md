# 3D viewer

This folder belongs to the 3D worker. WEB leaves the implementation to that worker.

`Viewer3D` mounts and disposes the three.js viewer, with orbit controls, a storey
dropdown, loading/error messages, and a picked-item details card:

```tsx
import { Viewer3D } from './viewer3d';

<Viewer3D
  doc_id={docId}
  onPick={(item_id) => console.log(item_id)}
/>
```

Give its parent a height (the component has a 420px minimum). `storey` defaults to
the lowest storey with a nonnegative elevation. Roofs and higher storeys are hidden.
The dropdown and previous/next buttons move the cutaway; `storey={null}` explicitly
shows all storeys. “Show roof” reveals roof geometry even above the selected storey,
while other higher-storey items stay hidden. Roofless extruded plans have no roof
control. Roof classification uses manifest `kind` and the optional IFC element
index (including `IfcSlab` with predefined type `ROOF` and roof coverings).
Clicks report the contract item ID; dragging only orbits.
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
`viewer.onHighlightChange(callback)` observes public highlight/clear calls and
returns an unsubscribe function. Internal scene disposal does not publish a clear.
Missing IDs are ignored; labels default to sequential numbers when omitted.
Answer and legacy live highlights use supplied citation numbers even when the
manifest has tags. Only scene commands and reconnect command snapshots resolve
missing labels from manifest tags (then item IDs); supplied command labels win.
An empty selection clears the highlight. State reports resolved item IDs,
the number of other resolved items (including hidden storeys), and label strings.
Highlighting selects the camera target's storey, otherwise the first highlighted
item's storey. Roof answers also reveal their roof geometry. These changes apply
to live updates and VisualisePanel too. `getCutawayState()` exposes `activeStorey`,
`showRoof`, and the number of hidden resolved items; `onCutawayChange(callback)`
observes updates. `setShowRoof(boolean)` controls the roof imperatively.
Keep React option references stable
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
The Document dropdown switches between DigitalHub, the light offline CubiCasa
`colorful-11397` fixture, and the real `ifc_bench__ac20-arc` API document.
`/?doc=colorful-11397#/viewer-test` selects the light fixture on first load
(the full `cubicasa5k__colorful-11397` ID is also accepted). Its GLB embeds its
texture; it needs no API geometry requests. Source credit and CC BY-NC-SA 4.0
terms are in `public/fixtures/colorful-11397/LICENSE.txt`; extruded heights are
labelled “generated for demo”. Only this test page exposes `window.viewer3dTest`
for browser helpers to position the camera and project a known item's bbox.

Validation: `npx vitest run src/viewer3d` and `npx tsc --noEmit` from `web/`.
The LEAD runs `scripts/heavy.sh` with
`npx playwright test e2e/viewer3d.spec.ts` from `web/` outside the worker sandbox.
The browser test uses SwiftShader and reads pixels during an animation frame;
more than 1% of the canvas must differ from the background. It also filters a
storey, clicks a rendered surface, and checks the returned ID against the fixture.
The LEAD also runs `npx playwright test e2e/viewer3d-highlight.spec.ts` through
`scripts/heavy.sh`. It uses the light fixture and reduced motion, waits for an
explicit renderer frame, and saves canvas clips with `page.screenshot` and
animations disabled. It checks the images differ, checks citation labels, and
clears the selection. Both highlight and live tests have a 60-second total timeout.
`e2e/viewer3d-identify.spec.ts` switches to AC20, projects a known Keller door's
bbox centre, clicks it, checks identity/storey, and dismisses the card. Its camera
sits within the opening so enclosing IFC space surfaces cannot intercept the
door click. The optional elements endpoint enriches the assertion when available.

For answer cards and documents, T-04 exports the ready-to-place button:

```tsx
import { VisualiseItButton, VisualisePanel } from './viewer3d';

<VisualiseItButton answer={answer} />
<VisualiseItButton docId={docId} />
// Or mount a controlled panel:
<VisualisePanel docId={docId} highlight={itemIds} labels={labelsByItemId} onClose={close} />
```

The button opens a modal with focus containment, Escape/Close dismissal and
focus restoration. The scene loads through the same API routes. It holds a
top-down flat plan for 600 ms, then eases wall/door/window Y scales to their
original values over 1200 ms while the camera moves into perspective. The
textured `plan_floor` stays readable. IFC scenes also begin top-down. Reduced
motion opens the completed view immediately. Orbit input finishes the rise
and gives the user camera control. Timer fallbacks advance the rise phases even
when animation frames are delayed; closing cancels these timers and disposes
the viewer and animation. The dialog reports `loading`, `flat`, `rising`, `done`,
or `error` through `data-rise-state`.
A missing scene displays “3D model not available for this document”.

`answerToVisualise` uses the scene document ID, the exact answer highlight IDs,
and the original box labels without renumbering. The dev page includes a document
ID input and a fake answer labelled “generated for demo”. Only this page exposes
`window.visualise3dTest.getHighlightState()` for the visualise browser test.
LEAD runs `scripts/heavy.sh` with
`npx playwright test e2e/viewer3d-visualise.spec.ts`; that test captures flat and
raised screenshots, checks the five IDs and labels, and covers missing scenes
and reduced motion. Its clock skips intermediate frames to keep software
rendering within the test timeout. The worker type-checks it because browser
launch is blocked in its sandbox.

T-06 connects every `Viewer3D` (including `VisualisePanel`) to the shared lazy
`/ws` client. Incoming `scene.highlight` events apply only to the open document;
updates arriving while geometry loads are retained. Item-card **Highlight**,
answer highlights, and imperative highlight/clear calls publish resolved IDs and
their citation labels. Remote application does not publish, and equal echoed
states do not restart the camera flight. The last viewer unsubscribing closes
the socket and cancels retries. Drops reconnect with capped exponential backoff;
the latest unsent selection per document is flushed on reconnect. Server `ping`
gets `pong`. Vite proxies `/ws`; HTTPS uses `wss://` at the current host.

`liveHighlight.ts` exports only `onHighlight(cb)` and
`sendHighlight(doc_id, item_ids, labels?)` for consumers. W-10 can replace those
functions with its general socket client; `bindLiveHighlight` accepts the same
two-method channel for integration/tests. The renderer has no socket dependency.
The server must relay optional `labels` to preserve nonsequential evidence numbers.

LEAD runs `scripts/heavy.sh` with
`npx playwright test e2e/viewer3d-live.spec.ts`. Two independent browser contexts
open the same light CubiCasa fixture, wait for socket handshakes, and verify three IDs,
sequential and custom labels, and a clear in both directions within two seconds.
Readiness observes the newest application socket's OPEN state: React StrictMode
closes the first socket during setup, so waiting for a probe on that socket can
hang. Geometry readiness allows 30 seconds under load; API/socket waits allow
nine seconds with named failures and timing logs. Both contexts close with
`Promise.allSettled` even on failure. The two-second sync assertions stay strict.
When using `scripts/test_snapshot.sh`, include `web/public/fixtures` alongside
`web/src/viewer3d` and the `viewer3d-*.spec.ts` files so the light assets are copied.

T-11 adds `e2e/viewer3d-cutaway.spec.ts`: real AC20 API metadata, initial ground
cutaway, roof visibility, storey stepping, highlight selection and live propagation
to VisualisePanel. A second case checks the light roofless extrusion. LEAD runs
this and the other viewer3d specs on the stable snapshot outside the sandbox.

T-12 accepts `commands={answer.evidence.scene.commands}` on `Viewer3D` and
`VisualisePanel`; `VisualiseItButton` forwards commands from its answer. A nonempty
command list takes precedence over legacy answer highlights. Equivalent rerenders
do not replay commands. Imperative hosts use `viewer.applyCommand(command)` and
`viewer.applyState(snapshot)`; `useLiveSceneCommands(viewer, docId)` binds those
hosts to `/ws` (Viewer3D already binds during scene loading). `onSceneEvent` and
`sendCommand` use the same shared socket as T-06. Commands retain arrival order
while loading/offline; edit IDs suppress server echoes. Snapshots replace the edit
layer. No source geometry or manifest is edited.

Command highlights use explicit labels, then manifest tags, then the item ID.
Hide removes the item's command label and fades out over 250 ms before disabling
its node. Restore reverses an in-flight hide from its current opacity; empty
restore restores all hidden items. Isolation restores its targets, highlights
them and dims other items. Reset clears hidden/highlighted/isolated state.
Cutaway visibility wins over edits; reduced motion applies visibility immediately.
The details card shows a manifest tag when available.

The test page also exposes `window.__viewer3d.getCommandState()`, returning copies
of `{hidden: string[], highlighted: Record<item_id,label>, isolated: string[]|null}`.
With `?viewer3dTest=1`, each canvas exposes `canvas.__viewer3d.commandState()`.
The new command e2e spec adds demo tags to fixture metadata, exercises answer
commands on the light extrusion, checks real `/ws` propagation to another browser
context within two seconds, and covers AC20 commands and fade interruption.
LEAD runs the handoff's full viewer3d suite through `scripts/heavy.sh` outside
the worker sandbox; Chromium cannot register its macOS Mach port inside it.

T-07 exposes `window.__viewer3d.perf()` on the dedicated test page: rendered
`frames`, RAF completion-interval `p50_ms`/`p95_ms`, latest-frame `draw_calls` and
`triangles`, and `load_ms` through the first scene render. `resetPerf()` starts a
fresh frame window without discarding load time. `?doc=<doc_id>#/viewer-test`
also accepts any API document. The performance spec finds the largest explicitly
publishable GLB under `artifacts/`, serves the actual files through intercepted
API routes, reveals every storey and roof, warms up rendering, and orbits for
five real seconds. It writes `results/viewer3d_perf.json` before asserting
`p95_ms < 33`. This spec uses the normal headless GPU path; the functional specs
retain their software-rendering settings. No timing result is inferred from
geometry counts or reported when browser launch fails.

Scenes with at least 500 meshes use separate render buffers: byte-identical
repeats (at least eight) use `InstancedMesh`; other compatible opaque geometry
shares `BatchedMesh` buffers by material. Original item meshes remain in the
item tree on a picking layer, with exact IDs, geometry and transforms. Changed
materials render through those originals until cleared; visibility and rise
transforms synchronize into batches when they change. Opaque batches retain
per-item frustum culling without depth sorting. Idle edit layers and empty label
trees skip traversal, pixel ratio stays capped at 2, shadows are disabled, and
scene replacement/unmount releases both original and batch resources. No mesh
decoder is needed by the largest current publishable GLB (no compression extension).

T-07 attempt 2 streams geometry with download progress. Static untextured GLBs
over 5 MiB parse in a bundled module worker with three.js `parseAsync`; typed
geometry buffers transfer ownership, including precomputed bounds. Rebuilding
the item hierarchy yields to the browser. Textures/animation and other unsupported
features retain the full glTF loader. Closing/replacing a scene aborts downloads
and terminates its worker. A 60-second load budget displays an error even when
an image/decoder promise stalls; any late scene is disposed. Source-material and
raycast-mesh indexes are deferred until interaction.

The perf spec has a 180-second timeout and a separate 150-second load expectation.
Its temporary HTTP server streams actual artifact GLBs, avoiding large base64
payloads over Playwright's control protocol. It tries publishable models in
descending file size and records attempted loads, including errors and elapsed
times. If the largest exceeds the 60-second load budget, it measures the next
largest candidate that loads within budget. Both the largest artifact and the
selected model remain in the report; unfinished loads have null `load_ms` rather
than an invented timing. Browser launch failures produce no benchmark result.

T-10 adds **Walk** to the viewer toolbar. It instantly places the camera 1.6 m
above the selected storey's floor: at `cameraTargetItemId` when supplied, otherwise
at the largest room's centroid (ground storey by default). Unsafe centroids fall
back to a clear nearby room position. WASD/arrows move at 2 m/s; dragging looks;
Q/PageDown and E/PageUp move between storeys. The existing storey controls and
incoming highlight storey changes also move the walker to the new floor. Escape
or toggling Walk off restores the saved orbit position, orientation, target and
near plane. Escape exits walking before dismissing an enclosing Visualise panel.

On touch screens the left joystick moves while a second finger drags the canvas
to look. Pointer cancellation, focus loss and backgrounding stop movement. There
is no head bob or camera transition, including with reduced motion enabled.
Collision sweeps a 0.3 m body against the original wall surfaces (both faces,
including meshes on the batch picking layer). Doors remain passable. Short
substeps prevent tunnelling, blocked movement slides along walls, and hidden
walls cease colliding until restored. Cutaway, labels and scene edits keep their
existing rendering paths; walking never modifies source geometry or materials.

`viewer.setWalk(boolean)` enters/exits; `viewer.walk()` returns
`{active, eye_height_m, storey, position}`. `onWalkChange(cb)` observes entry,
exit and floor changes; `setWalkJoystick(x, y)` supplies normalized touch input.
The dedicated test page exposes `window.__viewer3d.walk()`; opt-in canvas hooks
also expose `canvas.__viewer3d.walk()`. `e2e/viewer3d-walk.spec.ts` exercises real
AC20 desktop navigation, answer-target starts, edit retention and two-touch
phone controls. LEAD runs it and the full `viewer3d-*.spec.ts` set through
`scripts/heavy.sh` outside the sandbox (Chromium's macOS Mach port is blocked
inside it).

T-08 adds **Edit**: select an item, Remove through the existing hide/restore
commands, or Move by dragging on its horizontal floor plane (0.1 m snapping;
Escape cancels). Walls also offer Concrete, Timber frame and Glass as local
colour swaps, with the chosen material label. Undo and Reset edits reverse the
local history without changing the manifest or source files. Movement and
material swaps remain local; hide/restore use the shared command channel.

Each completed edit and inverse edit queues a POST to `/api/advise` after a
400 ms debounce. Requests retain operation order, including across slow calls,
and pass `{doc_id, chat_id?, edit: {op, item_ids, detail}}`. Optional `chat_id`
is a `Viewer3D` prop. Move details contain `delta_m`/`position_m`; material details
contain `material`. The existing shared `/ws` connection also receives scoped
`advisor.cards` events. Live responses supersede older in-flight HTTP responses.
At most three complete sourced cards render, with kind icons and expandable
source quotes. Card selection highlights its item IDs with manifest tags. Empty
responses say “No advice for this change.”; failed requests say advice is
unavailable. The server currently needs advisor-only move/material validation
and detail forwarding (recorded in the handoff).

`e2e/viewer3d-edit.spec.ts` uses the real AC20 scene and commands. Only its named
`advisor-fixture` response is stubbed, marked generated for demo; another test
uses the real advisor API. A third checks dragging, material requests, and reset.
The full browser done test remains for LEAD outside the worker sandbox.

T-09 adds an off-by-default Findings layer: GET loads stored findings, Run checks
POSTs the current document, and `findings.updated` refetches on the shared socket.
Pins use the first item's geometry bbox top centre, fixed screen size, and the
server's violation (red), suggestion (amber), and info (blue) severities. Findings
on one item share a count pin. Pins span all storeys so checks remain discoverable
in a cutaway; Show items uses the tagged highlight command to reveal the storey.
Cards quote the returned rule text and source without synthesising messages.
`window.__viewer3d.findings()` returns each finding's id, item_id, severity, and
viewport `screen_xy` (null outside the view). The opt-in canvas hook exposes it too.
`e2e/viewer3d-findings.spec.ts` exercises AC20 against the real API, including live
refresh, bbox projection, the card, tags, and toggle persistence.
Canvas click/tap tests finding sprites before building meshes; hover only picks
building items. Sprite picking updates world matrices and supplies the camera
through `Raycaster.setFromCamera`. The e2e test disables only the DOM pin pointer
targets to verify this canvas path, then restores them and opens the same card
with the pin button's Enter key.
