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
  - waiting for getByRole('dialog', { name: 'Drawing viewer', exact: true }).getByRole('button', { name: 'Fit drawing', exact: true })

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
    - link "Data" [ref=e21] [cursor=pointer]:
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
    - generic:
      - heading "Chat" [level=1]
      - generic:
        - button "New chat" [ref=e46] [cursor=pointer]
        - button [ref=e47] [cursor=pointer]
        - button [ref=e48] [cursor=pointer]
    - generic [ref=e49]:
      - region "Drawing questions" [ref=e50]:
        - article [ref=e52]:
          - generic [ref=e53]: How many windows are shown on this floor plan?
          - group [ref=e54]:
            - generic "› Show thought process" [ref=e55] [cursor=pointer]
          - paragraph [ref=e56]:
            - text: There are
            - strong [ref=e57]: 7 windows
            - text: on this floor plan.
            - button "Open citation 1" [pressed] [ref=e58] [cursor=pointer]: "1"
          - heading "Where it is set out" [level=3] [ref=e59]
          - list [ref=e60]:
            - listitem [ref=e61]:
              - generic [ref=e62]:
                - strong [ref=e63]: high_quality-108
                - text: (
                - button "Open source document high_quality-108" [ref=e64] [cursor=pointer]:
                  - generic [ref=e68]: high_quality-108
                - text: )
              - list [ref=e69]:
                - listitem [ref=e70]:
                  - text: Page 1 · 7 cited items
                  - button "Open citation 1" [pressed] [ref=e71] [cursor=pointer]: "1"
          - generic [ref=e72]:
            - group [ref=e73]:
              - generic "Sources 1" [ref=e74] [cursor=pointer]:
                - generic [ref=e78]: Sources
                - generic [ref=e79]: "1"
            - button "Play spoken answer" [ref=e81] [cursor=pointer]
            - generic "Answer cost $0.0000" [ref=e87]: $0.0000
        - generic [ref=e88]:
          - generic [ref=e89]:
            - generic "Selected documents" [ref=e90]:
              - generic [ref=e91]:
                - generic [ref=e95]: high_quality-108
                - button "Remove high_quality-108" [ref=e96] [cursor=pointer]
            - generic [ref=e100]:
              - generic [ref=e101]: Ask about your drawings
              - generic [aria-hidden]: Ask anything. Type @ to include a document
              - combobox "Ask about your drawings" [ref=e102]
            - generic [ref=e103]:
              - 'button "Document context: 1 selected" [ref=e104] [cursor=pointer]':
                - generic [ref=e106]: 1 selected
              - button "Speak a question" [ref=e113] [cursor=pointer]
              - button "Send question" [disabled] [ref=e117]
          - paragraph [ref=e118]: AI can make mistakes. Verify important information.
      - dialog "Drawing viewer" [ref=e119]:
        - generic [ref=e120]:
          - generic [ref=e124]:
            - strong [ref=e125]: high_quality-108
            - generic [ref=e126]: /cubicasa5k
          - generic [ref=e127]:
            - button "Previous source" [disabled] [ref=e128]
            - generic [ref=e129]: 1 of 7
            - button "Next source" [ref=e130] [cursor=pointer]
          - button "Close drawing viewer" [active] [ref=e131] [cursor=pointer]
        - generic "Drawing controls" [ref=e132]:
          - generic [ref=e133]:
            - generic [ref=e136]: "1"
            - generic [ref=e137]: / 1
          - link "Download drawing page" [ref=e149] [cursor=pointer]:
            - /url: blob:http://localhost:4183/ee35f544-d12d-4086-ba7f-822db20b152b
          - generic [ref=e153]:
            - button "Zoom out" [ref=e154] [cursor=pointer]
            - generic "Zoom level" [ref=e155]: 100%
            - button "Zoom in" [ref=e156] [cursor=pointer]
        - generic "Drawing canvas. Drag to pan, scroll or pinch to zoom. Arrow keys pan, plus and minus zoom, zero fits." [ref=e157]:
          - generic:
            - 'img "Drawing: high_quality-108, page 1"'
            - img "Numbered drawing evidence":
              - generic "Box 1" [ref=e158] [cursor=pointer]:
                - img [ref=e160]:
                  - generic [ref=e162]: "1"
              - generic "Box 2" [ref=e163] [cursor=pointer]:
                - img [ref=e165]:
                  - generic [ref=e167]: "2"
              - generic "Box 3" [ref=e168] [cursor=pointer]:
                - img [ref=e170]:
                  - generic [ref=e172]: "3"
              - generic "Box 4" [ref=e173] [cursor=pointer]:
                - img [ref=e175]:
                  - generic [ref=e177]: "4"
              - generic "Box 5" [ref=e178] [cursor=pointer]:
                - img [ref=e180]:
                  - generic [ref=e182]: "5"
              - generic "Box 6" [ref=e183] [cursor=pointer]:
                - img [ref=e185]:
                  - generic [ref=e187]: "6"
              - generic "Box 7" [ref=e188] [cursor=pointer]:
                - img [ref=e190]:
                  - generic [ref=e192]: "7"
        - button "Visualise it" [ref=e194] [cursor=pointer]
        - generic [ref=e195]: "CubiCasa5K, (c) 2019 CubiCasa. Kalervo, Ylioinas, Häikiö, Karhu, Kannala: 'CubiCasa5K: A Dataset and an Improved Multi-Task Model for Floorplan Image Analysis', SCIA 2019. CC BY-NC-SA 4.0. · CC-BY-NC-SA-4.0"
```

# Test source

```ts
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
  42  |   await details.locator('header').getByRole('button', { name: 'Ask about it', exact: true }).click()
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
> 129 |   await drawing.getByRole('button', { name: 'Fit drawing', exact: true }).click()
      |                                                                           ^ TimeoutError: locator.click: Timeout 15000ms exceeded.
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
  143 |     if (!canvas.__viewer3d) throw new Error('Opt-in __viewer3d handle is not ready')
  144 |     return { highlight: canvas.__viewer3d.state(), commands: canvas.__viewer3d.commandState() }
  145 |   })
  146 | }
  147 | 
  148 | export async function visualise(page: Page, drawing: Locator, answer: Answer) {
  149 |   await drawing.getByRole('button', { name: 'Visualise it', exact: true }).click()
  150 |   const panel = page.getByRole('dialog', { name: 'Visualise it', exact: true })
  151 |   await expect(panel.getByRole('region', { name: '3D viewer', exact: true })).toHaveAttribute('data-state', 'ready', { timeout: 60_000 })
  152 |   await expect(panel.getByText('3D view ready', { exact: true })).toBeVisible({ timeout: 60_000 })
  153 |   const expected = [...answer.evidence.scene.highlight_item_ids].sort()
  154 |   expect(expected.length).toBeGreaterThan(0)
  155 |   await expect.poll(async () => (await viewerState(panel)).highlight.highlighted.sort(), { timeout: 15_000 }).toEqual(expected)
  156 |   const state = await viewerState(panel)
  157 |   for (const box of answer.evidence.boxes) {
  158 |     expect(state.highlight.labels[box.item_id]).toBe(box.label)
  159 |     await expect(panel.getByLabel(`Item ${box.label}: ${box.item_id}`, { exact: true })).toHaveText(box.label)
  160 |   }
  161 |   return panel
  162 | }
  163 | 
```