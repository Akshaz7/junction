# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: demo-flow.spec.ts >> desktop: live raster proof carries into 3D, then AC20 door evidence and scene edits
- Location: e2e/demo-flow.spec.ts:17:1

# Error details

```
TimeoutError: locator.click: Timeout 15000ms exceeded.
Call log:
  - waiting for getByRole('complementary', { name: 'Document details' }).locator('header').getByRole('button', { name: 'Ask about it', exact: true })

```

# Page snapshot

```yaml
- generic [ref=e3]:
  - link "Skip to content" [ref=e4] [cursor=pointer]:
    - /url: "#main-content"
  - complementary "Workspace sidebar" [ref=e5]:
    - link "Hologram home" [ref=e6] [cursor=pointer]:
      - /url: "#/overview"
      - text: Hologram
    - generic [ref=e7]:
      - generic [aria-hidden] [ref=e8]: D
      - generic [ref=e9]: Project
      - combobox "Project" [ref=e10] [cursor=pointer]:
        - option "Construction project" [selected]
    - navigation "Workspace navigation" [ref=e11]:
      - link "Overview" [ref=e13] [cursor=pointer]:
        - /url: "#/overview"
      - link "Chat" [ref=e18] [cursor=pointer]:
        - /url: "#/chat"
      - link "Accuracy" [ref=e23] [cursor=pointer]:
        - /url: "#/accuracy"
      - link "Changes" [ref=e30] [cursor=pointer]:
        - /url: "#/changes"
      - link "Skills" [ref=e35] [cursor=pointer]:
        - /url: "#/skills"
      - link "Data" [ref=e39] [cursor=pointer]:
        - /url: "#/data"
      - link "Automations" [ref=e45] [cursor=pointer]:
        - /url: "#/automations"
      - link "More" [ref=e49] [cursor=pointer]:
        - /url: "#/accuracy"
    - generic [aria-hidden] [ref=e55]: AK
  - main [ref=e56]:
    - generic: Connected workspace
    - generic [ref=e58]:
      - heading "Data" [level=1] [ref=e59]
      - generic [ref=e60]: Documents
    - region "Project documents" [ref=e68]:
      - button "Upload" [ref=e70] [cursor=pointer]
      - generic:
        - generic:
          - text: Drop a drawing here, or use Upload.
          - generic: One file at a time · IFC, DXF, DWG, PDF, SVG, PNG, JPG, TIF · up to 100 MB
      - generic [ref=e71]:
        - navigation "Document folders" [ref=e72]:
          - heading "Folders" [level=2] [ref=e73]
          - button "All Files 786" [ref=e76] [cursor=pointer]:
            - generic [ref=e81]: All Files
            - generic [ref=e82]: "786"
          - generic [ref=e83]:
            - button "Open cubicasa5k folder" [ref=e84] [cursor=pointer]:
              - generic [ref=e87]: cubicasa5k
              - generic [ref=e88]: "241"
            - generic [ref=e89]:
              - button "Preview colorful-11397" [ref=e90] [cursor=pointer]:
                - generic [ref=e94]: colorful-11397
              - button "Preview colorful-11400" [ref=e96] [cursor=pointer]:
                - generic [ref=e100]: colorful-11400
              - button "Preview colorful-11960" [ref=e102] [cursor=pointer]:
                - generic [ref=e106]: colorful-11960
              - button "Preview colorful-12200" [ref=e108] [cursor=pointer]:
                - generic [ref=e112]: colorful-12200
              - button "Preview colorful-13685" [ref=e114] [cursor=pointer]:
                - generic [ref=e118]: colorful-13685
              - button "Preview colorful-1732" [ref=e120] [cursor=pointer]:
                - generic [ref=e124]: colorful-1732
              - button "Preview colorful-2002" [ref=e126] [cursor=pointer]:
                - generic [ref=e130]: colorful-2002
              - button "Preview colorful-2194" [ref=e132] [cursor=pointer]:
                - generic [ref=e136]: colorful-2194
              - button "Preview colorful-34" [ref=e138] [cursor=pointer]:
                - generic [ref=e142]: colorful-34
              - button "Preview colorful-6327" [ref=e144] [cursor=pointer]:
                - generic [ref=e148]: colorful-6327
          - button "Open europeana folder" [ref=e151] [cursor=pointer]:
            - generic [ref=e154]: europeana
            - generic [ref=e155]: "61"
          - button "Open finna folder" [ref=e157] [cursor=pointer]:
            - generic [ref=e160]: finna
            - generic [ref=e161]: "96"
          - button "Open habs folder" [ref=e163] [cursor=pointer]:
            - generic [ref=e166]: habs
            - generic [ref=e167]: "92"
          - button "Open ifc_bench folder" [ref=e169] [cursor=pointer]:
            - generic [ref=e172]: ifc_bench
            - generic [ref=e173]: "5"
          - button "Open ifc_models folder" [ref=e175] [cursor=pointer]:
            - generic [ref=e178]: ifc_models
            - generic [ref=e179]: "7"
          - button "Open opening_design folder" [ref=e181] [cursor=pointer]:
            - generic [ref=e184]: opening_design
            - generic [ref=e185]: "81"
          - button "Open swiss_dwellings folder" [ref=e187] [cursor=pointer]:
            - generic [ref=e190]: swiss_dwellings
            - generic [ref=e191]: "65"
          - button "Open uploads folder" [ref=e193] [cursor=pointer]:
            - generic [ref=e196]: uploads
            - generic [ref=e197]: "13"
          - button "Open wikimedia folder" [ref=e199] [cursor=pointer]:
            - generic [ref=e202]: wikimedia
            - generic [ref=e203]: "125"
        - searchbox "Search documents" [ref=e205]: cubicasa5k__high-quality-108
        - complementary "Document details" [ref=e206]:
          - generic [ref=e207]:
            - generic [ref=e211]:
              - heading "high_quality-108" [level=2] [ref=e212]
              - generic [ref=e214]: /cubicasa5k
            - link "Compare document revisions" [ref=e215] [cursor=pointer]:
              - /url: "#/changes"
              - generic [ref=e221]: Compare
            - button "Fit page" [ref=e222] [cursor=pointer]
            - button "Close document details" [active] [ref=e223] [cursor=pointer]
          - generic [ref=e227]:
            - generic [ref=e230]: "1"
            - generic [ref=e231]: / 1
            - link "Download page" [ref=e245] [cursor=pointer]:
              - /url: /api/docs/cubicasa5k__high-quality-108/pages/1/image
            - generic [ref=e250]:
              - button "Zoom out" [ref=e251] [cursor=pointer]
              - generic "Page zoom level" [ref=e252]: 100%
              - button "Zoom in" [ref=e253] [cursor=pointer]
          - generic [ref=e254]:
            - img "First page of high_quality-108" [ref=e258]
            - generic [ref=e259]:
              - generic [ref=e260]:
                - term [ref=e261]: Credit
                - definition [ref=e262]: "CubiCasa5K, (c) 2019 CubiCasa. Kalervo, Ylioinas, Häikiö, Karhu, Kannala: 'CubiCasa5K: A Dataset and an Improved Multi-Task Model for Floorplan Image Analysis', SCIA 2019. CC BY-NC-SA 4.0."
              - generic [ref=e263]:
                - term [ref=e264]: Licence
                - definition [ref=e265]: CC-BY-NC-SA-4.0
            - generic [ref=e266]:
              - button "Ask about it" [ref=e267] [cursor=pointer]
              - button "Visualise it" [ref=e268] [cursor=pointer]
            - status [ref=e269]: 3D scene available.
```

# Test source

```ts
  1   | import { mkdir } from 'node:fs/promises'
  2   | import { fileURLToPath } from 'node:url'
  3   | import { expect, test, type Locator, type Page } from '@playwright/test'
  4   | import type { Answer, Document } from '../src/lib/types'
  5   | import type { LinkedViewerCanvas } from '../src/viewer3d/Viewer3D'
  6   | import type { SceneCommand } from '../src/viewer3d/commands'
  7   | 
  8   | export const api = 'http://localhost:8000'
  9   | export const ac20 = 'ifc_bench__ac20-arc'
  10  | export const countQuestion = 'How many windows are shown on this floor plan?'
  11  | const screenshots = fileURLToPath(new URL('../../results/e2e/', import.meta.url))
  12  | type LiveAnswer = Answer & { evidence: { scene: { commands?: SceneCommand[] } } }
  13  | type StatusHost = Window & { __demoStatus?: { texts: string[]; observer: MutationObserver } }
  14  | 
  15  | export async function shot(page: Page, step: string) {
  16  |   await mkdir(screenshots, { recursive: true })
  17  |   await page.screenshot({ path: `${screenshots}/${step}.png`, fullPage: true })
  18  | }
  19  | 
  20  | export async function rasterPick(page: Page) {
  21  |   const primary = 'cubicasa5k__high-quality-108'
  22  |   const response = await page.request.get(`${api}/api/docs/${primary}`)
  23  |   if (response.status() !== 404) {
  24  |     expect(response.ok(), 'C01 must be reachable on the real API').toBe(true)
  25  |     return { doc: await response.json() as Document, gold: 7, candidate: 'C01' }
  26  |   }
  27  |   // C28 is allowed only when C01 is absent, never to mask a wrong answer.
  28  |   const fallback = await page.request.get(`${api}/api/docs/cubicasa5k__colorful-7513`)
  29  |   expect(fallback.ok(), 'Seed C01 or its documented C28 fallback').toBe(true)
  30  |   test.info().annotations.push({ type: 'demo-pick', description: 'C01 absent (404); using documented C28, gold 5.' })
  31  |   return { doc: await fallback.json() as Document, gold: 5, candidate: 'C28' }
  32  | }
  33  | 
  34  | export async function selectFromData(page: Page, doc: Document, phone: boolean) {
  35  |   const navigation = page.getByRole('navigation', { name: phone ? 'Mobile navigation' : 'Workspace navigation', exact: true })
  36  |   await navigation.getByRole('link', { name: 'Data', exact: true }).click()
  37  |   await page.getByRole('searchbox', { name: 'Search documents' }).fill(doc.doc_id)
  38  |   await page.locator(`[data-doc-id="${doc.doc_id}"] .data-open-file`).click()
  39  |   const details = page.getByRole('complementary', { name: 'Document details' })
  40  |   await expect(details).toBeVisible()
  41  |   // The header action is also available on phones, where the footer is hidden.
> 42  |   await details.locator('header').getByRole('button', { name: 'Ask about it', exact: true }).click()
      |                                                                                              ^ TimeoutError: locator.click: Timeout 15000ms exceeded.
  43  |   await expect(page).toHaveURL(/#\/chat(?:\?|$)/)
  44  |   await expect(page.getByLabel('Selected documents')).toContainText(doc.title)
  45  | }
  46  | 
  47  | function assertNoStub(value: unknown) {
  48  |   if (value === null || typeof value !== 'object') return
  49  |   for (const [key, child] of Object.entries(value)) {
  50  |     if (key === 'stub') expect(child, 'Real SSE must never contain stub: true').not.toBe(true)
  51  |     assertNoStub(child)
  52  |   }
  53  | }
  54  | 
  55  | /** Observe rendered statuses without delaying, intercepting or replacing any request. */
  56  | async function observeStatuses(page: Page) {
  57  |   await page.evaluate(() => {
  58  |     const host = window as StatusHost
  59  |     host.__demoStatus?.observer.disconnect()
  60  |     const texts: string[] = []
  61  |     const observer = new MutationObserver(() => {
  62  |       for (const node of document.querySelectorAll<HTMLElement>('.pending-exchange .thinking-text')) {
  63  |         const text = node.getAttribute('aria-label')
  64  |         if (text && node.getClientRects().length && getComputedStyle(node).visibility !== 'hidden' && texts.at(-1) !== text) texts.push(text)
  65  |       }
  66  |     })
  67  |     observer.observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ['aria-label'] })
  68  |     host.__demoStatus = { texts, observer }
  69  |   })
  70  | }
  71  | 
  72  | export async function ask(page: Page, question: string, docId: string, requireStatuses = false) {
  73  |   return test.step(`Ask live: ${question}`, async () => {
  74  |     const composer = page.getByRole('combobox', { name: 'Ask about your drawings' })
  75  |     await composer.fill(question)
  76  |     await observeStatuses(page)
  77  |     const responsePromise = page.waitForResponse((response) => response.request().method() === 'POST'
  78  |       && /\/api\/chats\/[^/]+\/messages$/.test(new URL(response.url()).pathname), { timeout: 60_000 })
  79  |     await page.getByRole('button', { name: 'Send question', exact: true }).click()
  80  |     const response = await responsePromise
  81  |     expect(response.ok(), 'The actual browser message POST must succeed').toBe(true)
  82  |     expect(response.headers()['content-type']).toContain('text/event-stream')
  83  |     expect(response.request().postDataJSON()).toEqual({ content: question, doc_ids: [docId] })
  84  |     const stream = await response.text()
  85  |     expect(stream, 'Scan the entire captured stream, including trace events').not.toMatch(/"stub"\s*:\s*true/)
  86  |     const events = stream.replace(/\r\n/g, '\n').split('\n\n').flatMap((block) => {
  87  |       const lines = block.split('\n')
  88  |       const event = lines.find((line) => line.startsWith('event:'))?.slice(6).trim()
  89  |       const data = lines.filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trimStart()).join('\n')
  90  |       if (!event || !data) return []
  91  |       const parsed: unknown = JSON.parse(data)
  92  |       assertNoStub(parsed)
  93  |       return [{ event, data: parsed }]
  94  |     })
  95  |     const answers = events.filter((event) => event.event === 'answer')
  96  |     expect(answers, 'Exactly one final answer in the real SSE').toHaveLength(1)
  97  |     const answer = answers[0].data as LiveAnswer
  98  |     expect(answer.answer.abstained).toBe(false)
  99  |     expect(answer.question).toBe(question)
  100 |     expect(answer.doc_ids).toEqual([docId])
  101 |     expect(answer.evidence.scene.doc_id).toBe(docId)
  102 |     expect(answer.trace.length).toBeGreaterThan(0)
  103 |     const statuses = await page.evaluate(() => (window as StatusHost).__demoStatus?.texts ?? [])
  104 |     await test.info().attach(`SSE ${question}`, { body: stream, contentType: 'text/event-stream' })
  105 |     await test.info().attach(`Rendered statuses ${question}`, { body: JSON.stringify(statuses), contentType: 'application/json' })
  106 |     if (requireStatuses) {
  107 |       expect(statuses, 'Thinking must actually render, even for a fast count').toContain('Thinking…')
  108 |       const apiStatuses = events.filter((event) => event.event === 'status').map((event) => (event.data as { text: string }).text)
  109 |       expect(apiStatuses.length, 'Backend must stream at least one status').toBeGreaterThan(0)
  110 |       expect(statuses.some((text) => text !== 'Thinking…' && apiStatuses.includes(text)),
  111 |         'At least one real backend status must appear in the UI').toBe(true)
  112 |     }
  113 |     const card = page.locator('.exchange').filter({ has: page.getByText(question, { exact: true }) }).last()
  114 |     await expect(card.locator('.answer-text')).toBeVisible()
  115 |     await expect(card.getByTestId('answer-cost')).toBeVisible()
  116 |     await expect(page.locator('.pending-exchange')).toHaveCount(0)
  117 |     return { answer, card }
  118 |   }, { timeout: 60_000 })
  119 | }
  120 | 
  121 | export async function openDrawing(page: Page, card: Locator, answer: Answer, phone: boolean) {
  122 |   await card.locator('.answer-text').getByRole('button', { name: `Open citation ${answer.citations[0].n}`, exact: true }).click()
  123 |   const drawing = page.getByRole(phone ? 'dialog' : 'region', { name: 'Drawing viewer', exact: true })
  124 |   await expect(drawing).toBeVisible()
  125 |   if (phone) await expect(drawing).toHaveAttribute('aria-modal', 'true')
  126 |   const image = drawing.getByRole('img', { name: /Drawing:/ })
  127 |   await expect(image).toBeVisible({ timeout: 15_000 })
  128 |   await expect.poll(() => image.evaluate((node: HTMLImageElement) => node.complete && node.naturalWidth > 0)).toBe(true)
  129 |   await drawing.getByRole('button', { name: 'Fit drawing', exact: true }).click()
  130 |   const boxes = drawing.locator('.evidence-region')
  131 |   const evidence = answer.evidence.boxes.filter((box) => box.page === answer.citations[0].page)
  132 |   await expect(boxes).toHaveCount(evidence.length)
  133 |   expect(evidence.length).toBeGreaterThan(0)
  134 |   expect(await boxes.evaluateAll((nodes) => nodes.map((node) => ({
  135 |     id: node.getAttribute('data-item-id'), label: node.querySelector('text')?.textContent,
  136 |   })))).toEqual(evidence.map((box) => ({ id: box.item_id, label: box.label })))
  137 |   await expect(drawing.getByTestId('drawing-credit')).toBeVisible()
  138 |   return drawing
  139 | }
  140 | 
  141 | export async function viewerState(panel: Locator) {
  142 |   return panel.locator('canvas').evaluate((canvas: LinkedViewerCanvas) => {
```