# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: e2e/viewer3d-x24.spec.ts >> 3D after "remove the front door": the removed door stays as a ghost with its glow and tag
- Location: e2e/viewer3d-x24.spec.ts:42:1

# Error details

```
Error: expect(received).toContain(expected) // indexOf

Expected value: "Door"
Received array: []
```

# Page snapshot

```yaml
- generic [ref=e3]:
  - link "Skip to content" [ref=e4] [cursor=pointer]:
    - /url: "#main-content"
  - complementary "Workspace sidebar" [ref=e5]:
    - link "Stoa Pro home" [ref=e6] [cursor=pointer]:
      - /url: "#/overview"
      - img "Stoa" [ref=e7]
      - generic [ref=e8]: Pro
    - navigation "Workspace navigation" [ref=e9]:
      - link "Overview" [ref=e11] [cursor=pointer]:
        - /url: "#/overview"
      - link "Chat" [ref=e16] [cursor=pointer]:
        - /url: "#/chat"
      - link "Compare" [ref=e21] [cursor=pointer]:
        - /url: "#/compare"
      - link "Changes" [ref=e28] [cursor=pointer]:
        - /url: "#/changes"
      - link "Library" [ref=e33] [cursor=pointer]:
        - /url: "#/library"
      - link "Data" [ref=e37] [cursor=pointer]:
        - /url: "#/data"
      - link "Tools" [ref=e43] [cursor=pointer]:
        - /url: "#/tools"
      - group [ref=e46]:
        - generic "More" [ref=e47] [cursor=pointer]
  - main [ref=e52]:
    - generic: Connected workspace
    - generic:
      - heading "Chat" [level=1]
      - generic:
        - button "New chat" [ref=e54] [cursor=pointer]
        - button "History" [ref=e55] [cursor=pointer]
        - button "Share" [ref=e56] [cursor=pointer]
        - button "Pair a phone" [ref=e58] [cursor=pointer]
    - generic [ref=e59]:
      - region "Drawing questions" [ref=e60]:
        - article [ref=e62]:
          - generic [ref=e63]: remove the front door
          - group [ref=e64]:
            - generic "› Show thought process" [ref=e65] [cursor=pointer]
          - paragraph [ref=e66]:
            - text: The front door (D34) on Erdgeschoss is hidden. 76 of 77 doors remain visible.
            - strong [ref=e67]: "Not compliant after this edit:"
            - text: Fewer than two exits left on Erdgeschoss (848/2017 §33).
            - button "Open citation 1" [pressed] [ref=e68] [cursor=pointer]: "1"
          - generic "Documents used" [ref=e69]:
            - button "Open document AC20 Institute / Phantasy Office Building - arc" [ref=e70] [cursor=pointer]:
              - generic [ref=e74]: AC20 Institute / Phantasy Office Building - arc
          - generic "Scene command items" [ref=e75]:
            - button "Show D34 on drawing, hidden" [ref=e76] [cursor=pointer]:
              - generic [ref=e77]: D34
              - generic [ref=e78]: hidden
            - button "Undo" [ref=e79] [cursor=pointer]
          - generic "Advice for this change" [ref=e83]:
            - article [ref=e84]:
              - generic [ref=e85] [cursor=pointer]:
                - generic [ref=e86]:
                  - img "Violation" [ref=e87]
                  - strong [ref=e89]: Fewer than two exits left on Erdgeschoss
                  - generic [ref=e90]: Violation
                - generic [ref=e91]: "Violation of 848/2017 §33: hiding D34 leaves 1 exit on Erdgeschoss. Two separate exits are required; small buildings can be an exception."
              - paragraph [ref=e92]: "Checked: Door width (241/2017 §4) · Entrance ramp (241/2017 §2) · Corridor turning space (241/2017 §5) · Exit width (848/2017 §34) · Exits per storey (848/2017 §33) · Headroom (1007/2017 §14)"
              - group [ref=e93]:
                - generic "Decree 848/2017 §33" [ref=e94] [cursor=pointer]
            - article [ref=e95]:
              - generic [ref=e96] [cursor=pointer]:
                - generic [ref=e97]:
                  - img "Suggestion" [ref=e98]
                  - strong [ref=e100]: Only 1 exit found on Erdgeschoss
                  - generic [ref=e101]: Suggestion
                - generic [ref=e102]: The model shows one outer door or stair on Erdgeschoss. Two separate exits are usual, though small buildings can be an exception. This is an inference from outer doors and stairs.
              - paragraph [ref=e103]: "Checked: Door width (241/2017 §4) · Entrance ramp (241/2017 §2) · Corridor turning space (241/2017 §5) · Exit width (848/2017 §34) · Exits per storey (848/2017 §33) · Headroom (1007/2017 §14)"
              - group [ref=e104]:
                - generic "Decree 848/2017 §33" [ref=e105] [cursor=pointer]
            - article [ref=e106]:
              - generic [ref=e107] [cursor=pointer]:
                - generic [ref=e108]:
                  - img "Suggestion" [ref=e109]
                  - strong [ref=e111]: Exit door D34 changed on Erdgeschoss
                  - generic [ref=e112]: Suggestion
                - generic [ref=e113]: D34 is an outer door of Erdgeschoss. Hiding it leaves 1 other exit counted there. Each evacuation area needs the number of separate exits in Table 11.
              - paragraph [ref=e114]: "Checked: Door width (241/2017 §4) · Entrance ramp (241/2017 §2) · Corridor turning space (241/2017 §5) · Exit width (848/2017 §34) · Exits per storey (848/2017 §33) · Headroom (1007/2017 §14)"
              - group [ref=e115]:
                - generic "Decree 848/2017 §33" [ref=e116] [cursor=pointer]
          - heading "Where it is set out" [level=3] [ref=e117]
          - list [ref=e118]:
            - listitem [ref=e119]:
              - generic [ref=e120]:
                - strong [ref=e121]: AC20 Institute / Phantasy Office Building - arc
                - text: (
                - button "Open source document AC20 Institute / Phantasy Office Building - arc" [ref=e122] [cursor=pointer]:
                  - generic [ref=e126]: AC20 Institute / Phantasy Office Building - arc
                - text: )
              - list [ref=e127]:
                - listitem [ref=e128]:
                  - text: Erdgeschoss · 1 staircase, 1 door
                  - button "Open citation 1" [pressed] [ref=e129] [cursor=pointer]: "1"
          - generic [ref=e130]:
            - group [ref=e131]:
              - generic "Sources 1" [ref=e132] [cursor=pointer]:
                - generic [ref=e136]: Sources
                - generic [ref=e137]: "1"
            - button "Play spoken answer" [ref=e139] [cursor=pointer]
            - button "Export report" [ref=e144] [cursor=pointer]
            - button "Visualise it" [ref=e150] [cursor=pointer]
            - generic "Answer cost $0.0000" [ref=e156]: $0.0000
        - generic [ref=e157]:
          - generic [ref=e158]:
            - generic "Selected documents" [ref=e159]:
              - generic [ref=e160]:
                - generic [ref=e164]: AC20 Institute / Phantasy Office Building - arc
                - button "Remove AC20 Institute / Phantasy Office Building - arc" [ref=e165] [cursor=pointer]
            - generic [ref=e169]:
              - generic [ref=e170]: Ask about your drawings
              - combobox "Ask about your drawings" [ref=e171]
            - generic [ref=e172]:
              - button "Add to question" [ref=e173] [cursor=pointer]
              - button "Speak a question" [ref=e176] [cursor=pointer]
              - button "Send question" [disabled] [ref=e180]
          - paragraph [ref=e181]: AI can make mistakes. Verify important information.
      - separator "Resize chat and drawing" [ref=e182]
      - region "Drawing viewer" [ref=e183]:
        - generic [ref=e184]:
          - generic [ref=e188]:
            - strong [ref=e189]: AC20 Institute / Phantasy Office Building - arc
            - generic [ref=e190]: /ifc_bench
          - group "Viewer mode" [ref=e191]:
            - button "2D" [ref=e192] [cursor=pointer]
            - button "3D" [pressed] [ref=e193] [cursor=pointer]
          - button "Close drawing viewer" [ref=e194] [cursor=pointer]
        - text: ·
        - region "3D model pane" [ref=e196]:
          - region "3D viewer" [ref=e197]:
            - generic [ref=e198]:
              - generic [ref=e199]: Storey
              - button "Previous storey" [ref=e200] [cursor=pointer]: −
              - combobox "Storey" [ref=e201]:
                - option "All storeys"
                - option "Keller"
                - option "Erdgeschoss"
                - option "1. Obergeschoss"
                - option "2. Obergeschoss" [selected]
                - option "Dachgeschoss"
              - button "Next storey" [ref=e202] [cursor=pointer]: +
              - generic [ref=e203]:
                - checkbox "Show roof" [ref=e204]
                - text: Show roof
              - button "Walk" [ref=e205] [cursor=pointer]
              - button "Edit" [ref=e206] [cursor=pointer]
              - button "Findings" [ref=e207] [cursor=pointer]
            - generic [ref=e208]:
              - generic "3D building model" [ref=e209]
              - generic:
                - generic: 42.0 m
                - generic: 16.0 m
                - generic: Keller · −3.00 m
                - generic: 1. Obergeschoss · +3.00 m
                - generic: 2. Obergeschoss · +6.00 m
            - group "Build-up steps" [ref=e211]:
              - button "Previous step" [ref=e212] [cursor=pointer]: ‹
              - button "Replay build-up" [ref=e213] [cursor=pointer]: Replay
              - button "Next step" [disabled] [ref=e214]: ›
              - slider "Build step" [ref=e215]: "17"
              - status [ref=e216]: Step 17 of 17 · 2. Obergeschoss doors and windows
        - generic [ref=e217]: Institute for Automation and Applied Informatics (IAI) / Karlsruhe Institute of Technology (KIT) - KIT IFC Examples, https://www.ifcwiki.org/index.php?title=KIT_IFC_Examples · LicenseRef-KIT-unrestricted
```

# Test source

```ts
  1  | import { expect, test } from '@playwright/test'
  2  | import type { LinkedViewerCanvas } from '../src/viewer3d/Viewer3D'
  3  | 
  4  | // X-24: opened from an answer, the answer's items are visible from the first frame of the build-up, and the storey
  5  | // selector agrees with the step label while it plays.
  6  | test.setTimeout(120_000)
  7  | const docId = 'ifc_bench__ac20-arc'
  8  | test('3D from an answer: highlights built from the first frame; selector follows the build step', async ({ page, request }, testInfo) => {
  9  |   const { id } = await (await request.post('http://localhost:8000/api/chats', { data: { doc_ids: [docId], title: 'X-24 3D' } })).json() as { id: string }
  10 |   const first = await request.post(`http://localhost:8000/api/chats/${id}/messages`, { data: { doc_ids: [docId], content: 'How many doors are there?' }, timeout: 60_000 })
  11 |   await first.text()
  12 |   await page.addInitScript(() => {
  13 |     const w = window as unknown as { __log: { t: number; hi: number; built: number; storey: string | null; step: string }[] }
  14 |     w.__log = []
  15 |     const tick = () => {
  16 |       const h = (document.querySelector('.drawing-model canvas') as LinkedViewerCanvas | null)?.__viewer3d
  17 |       if (h) {
  18 |         const ids = h.state().highlighted
  19 |         w.__log.push({ t: performance.now(), hi: ids.length, built: ids.filter((i) => (h.scaleY(i) ?? 0) > 0.99).length, ...h.storeyAndStep() })
  20 |       }
  21 |       requestAnimationFrame(tick)
  22 |     }
  23 |     requestAnimationFrame(tick)
  24 |   })
  25 |   await page.goto(`/?viewer3dTest=1#/chat?chat=${encodeURIComponent(id)}`)
  26 |   await page.getByRole('button', { name: /^Open citation/ }).first().click()
  27 |   const viewer = page.getByRole('region', { name: 'Drawing viewer', exact: true })
  28 |   await viewer.locator('.viewer3d-visualise-button').click()
  29 |   await expect(viewer.getByRole('region', { name: '3D viewer', exact: true })).toHaveAttribute('data-state', 'ready', { timeout: 90_000 })
  30 |   await expect(page.locator('.drawing-model')).toHaveAttribute('data-rise-state', 'done', { timeout: 90_000 })
  31 |   const log = await page.evaluate(() => (window as unknown as { __log: { t: number; hi: number; built: number; storey: string | null; step: string }[] }).__log)
  32 |   const withHi = log.filter((e) => e.hi > 0)
  33 |   const hidden = withHi.filter((e) => e.built < e.hi)
  34 |   const playing = (e: { step: string }) => { const m = /Step (\d+) of (\d+)/.exec(e.step); return !!m && m[1] !== m[2] }
  35 |   const mismatched = log.filter((e) => playing(e) && e.step && e.storey && !e.step.includes(`· ${e.storey} `) && !e.step.includes('· Roof') && !e.step.includes('Foundations'))
  36 |   console.log('frames', log.length, 'withHighlights', withHi.length, 'hiddenFrames', hidden.length, 'mismatch', mismatched.length, JSON.stringify(mismatched.slice(0, 2)))
  37 |   expect(withHi.length).toBeGreaterThan(5)
  38 |   expect(hidden.length).toBe(0)
  39 |   expect(mismatched.length).toBe(0)
  40 | })
  41 | 
  42 | test('3D after "remove the front door": the removed door stays as a ghost with its glow and tag', async ({ page, request }, testInfo) => {
  43 |   const { id } = await (await request.post('http://localhost:8000/api/chats', { data: { doc_ids: [docId], title: 'X-24 ghost' } })).json() as { id: string }
  44 |   await (await request.post(`http://localhost:8000/api/chats/${id}/messages`, { data: { doc_ids: [docId], content: 'remove the front door' }, timeout: 60_000 })).text()
  45 |   await page.goto(`/?viewer3dTest=1#/chat?chat=${encodeURIComponent(id)}`)
  46 |   await page.getByRole('button', { name: /^Open citation/ }).first().click()
  47 |   const viewer = page.getByRole('region', { name: 'Drawing viewer', exact: true })
  48 |   await viewer.locator('.viewer3d-visualise-button').click()
  49 |   await expect(page.locator('.drawing-model')).toHaveAttribute('data-rise-state', 'done', { timeout: 90_000 })
  50 |   await page.waitForTimeout(1500)
  51 |   const r = await page.evaluate(() => {
  52 |     const h = (document.querySelector('.drawing-model canvas') as LinkedViewerCanvas).__viewer3d!
  53 |     const ids = h.state().highlighted
  54 |     return { ids, drawn: ids.map((i) => h.drawn(i)), tags: [...document.querySelectorAll('.drawing-model .viewer3d-label-kind')].map((e) => e.textContent), legend: [...document.querySelectorAll('.drawing-model [data-testid="kind-legend"] li')].map((e) => e.textContent) }
  55 |   })
  56 |   console.log(JSON.stringify(r))
  57 |   await page.screenshot({ path: testInfo.outputPath('ghost.png') })
  58 |   expect(r.drawn.every(Boolean)).toBe(true)
> 59 |   expect(r.tags).toContain('Door')
     |                  ^ Error: expect(received).toContain(expected) // indexOf
  60 | })
  61 | 
```