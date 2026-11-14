# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: demo-flow.spec.ts >> desktop: live raster proof carries into 3D, then AC20 door evidence and scene edits
- Location: e2e/demo-flow.spec.ts:17:1

# Error details

```
Error: C20 must resolve the real manifest tag W3

expect(received).toBeTruthy()

Received: undefined
```

# Page snapshot

```yaml
- generic [ref=f1e1]:
  - generic [ref=f1e3]:
    - link "Skip to content" [ref=f1e4] [cursor=pointer]:
      - /url: "#main-content"
    - complementary "Workspace sidebar" [ref=f1e5]:
      - link "Hologram home" [ref=f1e6] [cursor=pointer]:
        - /url: "#/overview"
        - text: Hologram
      - generic [ref=f1e7]:
        - generic [aria-hidden] [ref=f1e8]: D
        - generic [ref=f1e9]: Project
        - combobox "Project" [ref=f1e10] [cursor=pointer]:
          - option "Construction project" [selected]
      - navigation "Workspace navigation" [ref=f1e11]:
        - link "Overview" [ref=f1e13] [cursor=pointer]:
          - /url: "#/overview"
        - link "Chat" [ref=f1e18] [cursor=pointer]:
          - /url: "#/chat"
        - link "Accuracy" [ref=f1e23] [cursor=pointer]:
          - /url: "#/accuracy"
        - link "Changes" [ref=f1e30] [cursor=pointer]:
          - /url: "#/changes"
        - link "Skills" [ref=f1e35] [cursor=pointer]:
          - /url: "#/skills"
        - link "Data" [ref=f1e39] [cursor=pointer]:
          - /url: "#/data"
        - link "Automations" [ref=f1e45] [cursor=pointer]:
          - /url: "#/automations"
        - link "More" [ref=f1e49] [cursor=pointer]:
          - /url: "#/accuracy"
      - generic [aria-hidden] [ref=f1e55]: AK
    - main [ref=f1e56]:
      - generic: Connected workspace
      - generic:
        - heading "Chat" [level=1]
        - generic:
          - button "New chat" [ref=f1e58] [cursor=pointer]:
            - generic [ref=f1e59]: New
          - button "History" [ref=f1e60] [cursor=pointer]
          - button "Share" [ref=f1e62] [cursor=pointer]
      - generic [ref=f1e64]:
        - region "Drawing questions" [ref=f1e65]:
          - article [ref=f1e67]:
            - generic [ref=f1e68]: What is the narrowest door width used here?
            - group [ref=f1e69]:
              - generic "› Show thought process" [ref=f1e70] [cursor=pointer]
            - paragraph [ref=f1e71]:
              - strong [ref=f1e72]: "Narrowest door: Tür-014 (IFC Tür - Eine Öffnunsgrichtung) 1 m"
              - button "Open citation 1" [pressed] [ref=f1e73] [cursor=pointer]: "1"
            - heading "Where it is set out" [level=3] [ref=f1e74]
            - list [ref=f1e75]:
              - listitem [ref=f1e76]:
                - generic [ref=f1e77]:
                  - strong [ref=f1e78]: AC20
                  - text: (
                  - button "Open source document AC20" [ref=f1e79] [cursor=pointer]:
                    - generic [ref=f1e83]: AC20
                  - text: )
                - list [ref=f1e84]:
                  - listitem [ref=f1e85]:
                    - text: Page 1 · 1 cited item
                    - button "Open citation 1" [pressed] [ref=f1e86] [cursor=pointer]: "1"
            - generic [ref=f1e87]:
              - group [ref=f1e88]:
                - generic "Sources 1" [ref=f1e89] [cursor=pointer]:
                  - generic [ref=f1e93]: Sources
                  - generic [ref=f1e94]: "1"
              - button "Play spoken answer" [ref=f1e96] [cursor=pointer]
              - generic "Answer cost $0.0000" [ref=f1e102]: $0.0000
          - generic [ref=f1e103]:
            - generic [ref=f1e104]:
              - generic "Selected documents" [ref=f1e105]:
                - generic [ref=f1e106]:
                  - generic [ref=f1e110]: AC20
                  - button "Remove AC20" [ref=f1e111] [cursor=pointer]
              - generic [ref=f1e115]:
                - generic [ref=f1e116]: Ask about your drawings
                - combobox "Ask about your drawings" [ref=f1e117]
              - generic [ref=f1e118]:
                - 'button "Document context: 1 selected" [ref=f1e119] [cursor=pointer]':
                  - generic [ref=f1e121]: 1 selected
                - button "Speak a question" [ref=f1e128] [cursor=pointer]
                - button "Send question" [disabled] [ref=f1e132]
            - paragraph [ref=f1e133]: AI can make mistakes. Verify important information.
        - separator "Resize chat and drawing" [ref=f1e134]
        - region "Drawing viewer" [ref=f1e135]:
          - generic [ref=f1e136]:
            - generic [ref=f1e140]:
              - strong [ref=f1e141]: AC20
              - generic [ref=f1e142]: /ifc_bench
            - generic [ref=f1e143]:
              - link "Open source page" [ref=f1e144] [cursor=pointer]:
                - /url: blob:http://localhost:4183/fc789009-13c4-4afa-b54b-52aa53ca5923
              - button "Previous source" [disabled] [ref=f1e149]
              - generic [ref=f1e150]: 0 of 0
              - button "Next source" [disabled] [ref=f1e153]
              - button "Fit drawing" [ref=f1e154] [cursor=pointer]
            - button "Close drawing viewer" [ref=f1e155] [cursor=pointer]
          - generic "Drawing controls" [ref=f1e156]:
            - generic [ref=f1e157]:
              - generic [ref=f1e160]: "1"
              - generic [ref=f1e161]: / 1
            - link "Download drawing page" [ref=f1e173] [cursor=pointer]:
              - /url: blob:http://localhost:4183/fc789009-13c4-4afa-b54b-52aa53ca5923
            - generic [ref=f1e178]:
              - button "Zoom out" [ref=f1e179] [cursor=pointer]
              - generic "Zoom level" [ref=f1e180]: 100%
              - button "Zoom in" [ref=f1e181] [cursor=pointer]
          - generic "Drawing canvas. Drag to pan, scroll or pinch to zoom. Arrow keys pan, plus and minus zoom, zero fits." [ref=f1e182]:
            - generic:
              - 'img "Drawing: AC20, page 1"'
              - img "Numbered drawing evidence"
          - button "Visualise it" [ref=f1e184] [cursor=pointer]
          - generic [ref=f1e185]: Credit not supplied · Licence not supplied
  - dialog "Visualise it" [ref=f1e186]:
    - banner [ref=f1e187]:
      - generic [ref=f1e188]:
        - heading "Visualise it" [level=2] [ref=f1e189]
        - paragraph [ref=f1e190]: ifc_bench__ac20-arc
      - button "Close 3D view" [active] [ref=f1e191] [cursor=pointer]: Close
    - region "3D viewer" [ref=f1e192]:
      - generic [ref=f1e193]:
        - generic [ref=f1e194]: Storey
        - button "Previous storey" [disabled] [ref=f1e195]: −
        - combobox "Storey" [ref=f1e196]:
          - option "All storeys"
          - option "Keller" [selected]
          - option "Erdgeschoss"
          - option "1. Obergeschoss"
          - option "2. Obergeschoss"
          - option "Dachgeschoss"
        - button "Next storey" [ref=f1e197] [cursor=pointer]: +
        - generic [ref=f1e198]:
          - checkbox "Show roof" [ref=f1e199]
          - text: Show roof
        - button "Walk" [ref=f1e200] [cursor=pointer]
      - generic [ref=f1e201]:
        - generic "3D building model" [ref=f1e202]
        - generic:
          - 'generic "Item 1: 3qloCPnZDEQBom1ZjBlwJP"': "1"
      - generic [ref=f1e203]:
        - paragraph [ref=f1e204]: Drag to orbit · Scroll to zoom · Click an item to identify it
        - status "Picked item" [ref=f1e205]: No item selected
    - status [ref=f1e206]: 3D view ready
```

# Test source

```ts
  1   | import { expect, test } from '@playwright/test'
  2   | import type { Document } from '../src/lib/types'
  3   | import { ac20, api, ask, countQuestion, openDrawing, rasterPick, selectFromData, shot, viewerState, visualise } from './demo-helpers'
  4   | 
  5   | // Live stack only: start the API on :8000 and seed docs/DEMO.md's picks.
  6   | // Every ask has its own 60 s deadline; the desktop scenario makes five asks.
  7   | test.use({
  8   |   viewport: { width: 1280, height: 800 },
  9   |   actionTimeout: 15_000,
  10  |   launchOptions: {
  11  |     executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
  12  |     args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
  13  |   },
  14  | })
  15  | test.setTimeout(420_000)
  16  | 
  17  | test('desktop: live raster proof carries into 3D, then AC20 door evidence and scene edits', async ({ page }) => {
  18  |   const raster = await rasterPick(page)
  19  |   await page.goto('/?viewer3dTest=1#/overview')
  20  |   await expect(page.getByText('Connected workspace', { exact: true })).toBeVisible()
  21  |   await selectFromData(page, raster.doc, false)
  22  |   await shot(page, 'desktop-01-raster-selected')
  23  | 
  24  |   const counted = await ask(page, countQuestion, raster.doc.doc_id, true)
  25  |   expect(counted.answer.answer.value, raster.candidate).toBe(raster.gold)
  26  |   await expect(counted.card.locator('.answer-text strong')).toContainText(new RegExp(`\\b${raster.gold}\\b`))
  27  |   expect(counted.answer.citations.length).toBeGreaterThan(0)
  28  |   await expect(counted.card.locator('.answer-text .citation-chip').first()).toBeVisible()
  29  |   await shot(page, 'desktop-02-raster-answer')
  30  | 
  31  |   const drawing = await openDrawing(page, counted.card, counted.answer, false)
  32  |   expect(counted.answer.evidence.boxes).toHaveLength(raster.gold)
  33  |   expect([...new Set(counted.answer.evidence.boxes.map((box) => box.item_id))].sort())
  34  |     .toEqual([...counted.answer.evidence.scene.highlight_item_ids].sort())
  35  |   await shot(page, 'desktop-03-numbered-drawing')
  36  |   const rasterPanel = await visualise(page, drawing, counted.answer)
  37  |   await shot(page, 'desktop-04-raster-3d')
  38  |   await rasterPanel.getByRole('button', { name: 'Close 3D view', exact: true }).click()
  39  |   await drawing.getByRole('button', { name: 'Close drawing viewer', exact: true }).click()
  40  | 
  41  |   // Start a fresh UI chat so the raster count's selected document cannot leak into C13.
  42  |   const metadata = await page.request.get(`${api}/api/docs/${ac20}`)
  43  |   expect(metadata.ok()).toBe(true)
  44  |   const building = await metadata.json() as Document
  45  |   await page.goto('/?viewer3dTest=1#/overview')
  46  |   await page.reload()
  47  |   await expect(page.getByText('Connected workspace', { exact: true })).toBeVisible()
  48  |   await selectFromData(page, building, false)
  49  |   await shot(page, 'desktop-05-ac20-selected')
  50  |   const narrowest = await ask(page, 'What is the narrowest door width used here?', ac20)
  51  |   await expect(narrowest.card.locator('.answer-text')).toContainText(/\b1(?:\.0+)?\s*m\b/)
  52  |   expect(narrowest.answer.citations).toHaveLength(1)
  53  |   expect(narrowest.answer.citations[0].item_ids).toHaveLength(1)
  54  |   expect(narrowest.answer.evidence.scene.highlight_item_ids).toEqual(narrowest.answer.citations[0].item_ids)
  55  |   await shot(page, 'desktop-06-narrowest-door-answer')
  56  |   await narrowest.card.locator('.answer-text').getByRole('button', { name: 'Open citation 1', exact: true }).click()
  57  |   const buildingDrawing = page.getByRole('region', { name: 'Drawing viewer', exact: true })
  58  |   const buildingPanel = await visualise(page, buildingDrawing, narrowest.answer)
  59  |   await expect(buildingPanel).toHaveClass(/viewer3d-linked-panel/)
  60  |   await shot(page, 'desktop-07-narrowest-door-3d')
  61  | 
  62  |   const sceneResponse = await page.request.get(`${api}/api/docs/${ac20}/scene`)
  63  |   expect(sceneResponse.ok()).toBe(true)
  64  |   const scene = await sceneResponse.json() as { items: Record<string, { kind: string; tag?: string }> }
  65  |   const doorIds = Object.entries(scene.items).filter(([, item]) => item.kind === 'door').map(([id]) => id).sort()
  66  |   expect(doorIds, 'C23 gold from docs/DEMO.md').toHaveLength(77)
  67  |   const w3 = Object.entries(scene.items).find(([, item]) => item.tag === 'W3')?.[0]
> 68  |   expect(w3, 'C20 must resolve the real manifest tag W3').toBeTruthy()
      |                                                           ^ Error: C20 must resolve the real manifest tag W3
  69  | 
  70  |   const doors = await ask(page, 'show only the doors', ac20)
  71  |   expect(doors.answer.evidence.scene.commands).toContainEqual(expect.objectContaining({ op: 'isolate', item_ids: expect.arrayContaining(doorIds) }))
  72  |   await buildingPanel.getByLabel('Storey', { exact: true }).selectOption('')
  73  |   await expect.poll(async () => {
  74  |     const state = await viewerState(buildingPanel)
  75  |     return {
  76  |       isolated: state.commands.isolated?.slice().sort(),
  77  |       highlighted: state.highlight.highlighted.slice().sort(),
  78  |       visibleDoors: doorIds.filter((id) => !state.commands.hidden.includes(id) && state.commands.isolated?.includes(id)).length,
  79  |     }
  80  |   }, { timeout: 15_000 }).toEqual({ isolated: doorIds, highlighted: doorIds, visibleDoors: 77 })
  81  |   await shot(page, 'desktop-08-only-doors')
  82  | 
  83  |   const removed = await ask(page, 'remove W3', ac20)
  84  |   expect(removed.answer.evidence.scene.commands).toContainEqual(expect.objectContaining({ op: 'hide', item_ids: [w3] }))
  85  |   await expect.poll(async () => (await viewerState(buildingPanel)).commands.hidden, { timeout: 15_000 }).toContain(w3)
  86  |   await shot(page, 'desktop-09-w3-hidden')
  87  | 
  88  |   const reset = await ask(page, 'reset', ac20)
  89  |   expect(reset.answer.evidence.scene.commands).toContainEqual(expect.objectContaining({ op: 'reset' }))
  90  |   await expect.poll(async () => (await viewerState(buildingPanel)).commands, { timeout: 15_000 })
  91  |     .toEqual({ hidden: [], highlighted: {}, isolated: null })
  92  |   await expect.poll(async () => (await viewerState(buildingPanel)).highlight.highlighted).toEqual([])
  93  |   await shot(page, 'desktop-10-reset')
  94  | })
  95  | 
  96  | test('phone: bottom tabs lead to a live count and full-screen numbered drawing sheet', async ({ page }) => {
  97  |   await page.setViewportSize({ width: 390, height: 844 })
  98  |   const raster = await rasterPick(page)
  99  |   await page.goto('/?viewer3dTest=1#/overview')
  100 |   await expect(page.getByText('Connected workspace', { exact: true })).toBeVisible()
  101 |   const tabs = page.getByRole('navigation', { name: 'Mobile navigation', exact: true })
  102 |   for (const label of ['Overview', 'Chat', 'Changes', 'Data']) {
  103 |     await expect(tabs.getByRole('link', { name: label, exact: true })).toBeInViewport()
  104 |   }
  105 |   await selectFromData(page, raster.doc, true)
  106 |   await expect(tabs.getByRole('link', { name: 'Chat', exact: true })).toHaveAttribute('aria-current', 'page')
  107 |   await shot(page, 'phone-01-raster-selected')
  108 |   const counted = await ask(page, countQuestion, raster.doc.doc_id, true)
  109 |   expect(counted.answer.answer.value, raster.candidate).toBe(raster.gold)
  110 |   await expect(counted.card.locator('.answer-text strong')).toContainText(new RegExp(`\\b${raster.gold}\\b`))
  111 |   await expect(counted.card.locator('.answer-text .citation-chip').first()).toBeVisible()
  112 |   await shot(page, 'phone-02-raster-answer')
  113 | 
  114 |   const drawing = await openDrawing(page, counted.card, counted.answer, true)
  115 |   expect(counted.answer.evidence.boxes).toHaveLength(raster.gold)
  116 |   await expect.poll(async () => {
  117 |     const bounds = await drawing.boundingBox()
  118 |     return !!bounds && bounds.x <= 1 && bounds.y <= 1 && bounds.width >= 389 && bounds.height >= 843
  119 |   }).toBe(true)
  120 |   await shot(page, 'phone-03-fullscreen-evidence')
  121 |   await drawing.getByRole('button', { name: 'Close drawing viewer', exact: true }).click()
  122 |   for (const label of ['Overview', 'Chat', 'Changes', 'Data']) {
  123 |     await expect(tabs.getByRole('link', { name: label, exact: true })).toBeVisible()
  124 |     await expect(tabs.getByRole('link', { name: label, exact: true })).toBeInViewport()
  125 |   }
  126 |   await tabs.getByRole('link', { name: 'Data', exact: true }).click()
  127 |   await expect(page).toHaveURL(/#\/data$/)
  128 |   await tabs.getByRole('link', { name: 'Chat', exact: true }).click()
  129 |   await expect(counted.card.locator('.answer-text strong')).toContainText(`${raster.gold}`)
  130 |   await shot(page, 'phone-04-tabs-return-to-answer')
  131 | })
  132 | 
```