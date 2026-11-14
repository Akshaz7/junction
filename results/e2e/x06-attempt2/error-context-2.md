# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: demo-flow.spec.ts >> phone: bottom tabs lead to a live count and full-screen numbered drawing sheet
- Location: e2e/demo-flow.spec.ts:96:1

# Error details

```
TimeoutError: locator.click: Timeout 15000ms exceeded.
Call log:
  - waiting for getByRole('navigation', { name: 'Mobile navigation', exact: true }).getByRole('link', { name: 'Chat', exact: true })
    - locator resolved to <a href="#/chat" aria-current="page">…</a>
  - attempting click action
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <img loading="lazy" alt="First page of high_quality-108" src="/api/docs/cubicasa5k__high-quality-108/pages/1/image"/> from <main tabindex="-1" class="workspace" id="main-content">…</main> subtree intercepts pointer events
    - retrying click action
    - waiting 20ms
    - waiting for element to be visible, enabled and stable
    - element is visible, enabled and stable
    - scrolling into view if needed
    - done scrolling
    - <img loading="lazy" alt="First page of high_quality-108" src="/api/docs/cubicasa5k__high-quality-108/pages/1/image"/> from <main tabindex="-1" class="workspace" id="main-content">…</main> subtree intercepts pointer events
  2 × retrying click action
      - waiting 100ms
      - waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div class="data-page-canvas">…</div> from <main tabindex="-1" class="workspace" id="main-content">…</main> subtree intercepts pointer events
  28 × retrying click action
       - waiting 500ms
       - waiting for element to be visible, enabled and stable
       - element is visible, enabled and stable
       - scrolling into view if needed
       - done scrolling
       - <div class="data-page-canvas">…</div> from <main tabindex="-1" class="workspace" id="main-content">…</main> subtree intercepts pointer events
  - retrying click action
    - waiting 500ms

```

# Page snapshot

```yaml
- generic [ref=e3]:
  - link "Skip to content" [ref=e4] [cursor=pointer]:
    - /url: "#main-content"
  - navigation "Mobile navigation" [ref=e5]:
    - link "Overview" [ref=e6] [cursor=pointer]:
      - /url: "#/overview"
    - link "Chat" [ref=e11] [cursor=pointer]:
      - /url: "#/chat"
    - link "Changes" [ref=e16] [cursor=pointer]:
      - /url: "#/changes"
    - link "Data" [active] [ref=e21] [cursor=pointer]:
      - /url: "#/data"
    - group [ref=e27]:
      - generic "More pages" [ref=e28] [cursor=pointer]: More
  - main [ref=e34]:
    - generic [ref=e35]:
      - generic [ref=e38]:
        - generic [aria-hidden] [ref=e39]: D
        - generic [ref=e40]: Project
        - combobox "Project" [ref=e41] [cursor=pointer]:
          - option "Construction project" [selected]
      - generic [ref=e45]: Connected workspace
    - generic [ref=e46]:
      - heading "Data" [level=1] [ref=e47]
      - generic [ref=e48]: Documents
    - text: ›
    - region "Project documents" [ref=e54]:
      - button "Upload" [ref=e56] [cursor=pointer]
      - generic:
        - generic:
          - text: Drop a drawing here, or use Upload.
          - generic: One file at a time · IFC, DXF, DWG, PDF, SVG, PNG, JPG, TIF · up to 100 MB
      - generic [ref=e57]:
        - searchbox "Search documents" [ref=e59]: cubicasa5k__high-quality-108
        - generic [ref=e60]:
          - generic [ref=e61]:
            - combobox "Document folder" [ref=e64]:
              - option "All Files"
              - option "cubicasa5k" [selected]
              - option "europeana"
              - option "finna"
              - option "habs"
              - option "ifc_bench"
              - option "ifc_models"
              - option "opening_design"
              - option "swiss_dwellings"
              - option "uploads"
              - option "wikimedia"
            - generic [ref=e66]: Files (1)
          - article [ref=e68]:
            - button "Open high_quality-108" [expanded] [ref=e69] [cursor=pointer]:
              - generic [ref=e76]:
                - heading "high_quality-108" [level=3] [ref=e77]
                - generic [ref=e79]: cubicasa5k · 1 page
          - generic "Document pagination" [ref=e80]:
            - generic [ref=e81]: 1–1 of 1
            - button "Previous document page" [disabled] [ref=e82]
            - generic [ref=e83]: Page 1 of 1
            - button "Next document page" [disabled] [ref=e84]
        - complementary "Document details" [ref=e85]:
          - generic [ref=e86]:
            - generic [ref=e90]:
              - heading "high_quality-108" [level=2] [ref=e91]
              - generic [ref=e93]: /cubicasa5k
              - group [ref=e94]:
                - generic "Drawing credit and licence" [ref=e95] [cursor=pointer]
            - button "Ask about it" [ref=e98] [cursor=pointer]
            - link "Compare document revisions" [ref=e101] [cursor=pointer]:
              - /url: "#/changes"
            - button "Close document details" [ref=e107] [cursor=pointer]
          - generic [ref=e111]:
            - generic [ref=e114]: "1"
            - generic [ref=e115]: / 1
            - link "Download page" [ref=e129] [cursor=pointer]:
              - /url: /api/docs/cubicasa5k__high-quality-108/pages/1/image
            - generic [ref=e133]:
              - button "Zoom out" [ref=e134] [cursor=pointer]
              - generic "Page zoom level" [ref=e135]: 40%
              - button "Zoom in" [ref=e136] [cursor=pointer]
          - img "First page of high_quality-108" [ref=e141]
```

# Test source

```ts
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
  68  |   expect(w3, 'C20 must resolve the real manifest tag W3').toBeTruthy()
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
> 128 |   await tabs.getByRole('link', { name: 'Chat', exact: true }).click()
      |                                                               ^ TimeoutError: locator.click: Timeout 15000ms exceeded.
  129 |   await expect(counted.card.locator('.answer-text strong')).toContainText(`${raster.gold}`)
  130 |   await shot(page, 'phone-04-tabs-return-to-answer')
  131 | })
  132 | 
```