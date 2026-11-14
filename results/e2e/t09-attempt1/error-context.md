# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: viewer3d-findings.spec.ts >> real AC20 checks pin the fire-exit finding above its item and show the sourced rule and tags
- Location: e2e/viewer3d-findings.spec.ts:19:1

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByRole('region', { name: '3D viewer', exact: true }).getByRole('complementary', { name: 'Finding details' }).getByRole('heading', { name: 'fi-fire-exits-per-storey', exact: true })
Expected: visible
Timeout: 5000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" getByRole('region', { name: '3D viewer', exact: true }).getByRole('complementary', { name: 'Finding details' }).getByRole('heading', { name: 'fi-fire-exits-per-storey', exact: true }) with timeout 5000ms
  - waiting for getByRole('region', { name: '3D viewer', exact: true }).getByRole('complementary', { name: 'Finding details' }).getByRole('heading', { name: 'fi-fire-exits-per-storey', exact: true })

```

```yaml
- main:
  - heading "AC20 — 3D viewer" [level=1]
  - paragraph: Institute for Automation and Applied Informatics (IAI) / Karlsruhe Institute of Technology (KIT) · KIT IFC Examples
  - text: Document
  - combobox "Document":
    - option "DigitalHub (offline fixture)"
    - option "CubiCasa colorful-11397 (light offline fixture)"
    - option "AC20 (API)" [selected]
  - button "Highlight 3 random items"
  - button "Clear highlight"
  - button "Highlight all windows"
  - button "Hide W3"
  - button "Restore W3"
  - status "Highlight state": "{\"highlighted\":[],\"dimmed\":0,\"labels\":{}}"
  - region "Visualise an answer":
    - text: Visualise document ID
    - textbox "Visualise document ID": cubicasa5k__colorful-11397
    - paragraph: "Fake answer — generated for demo: highlight window-001 through window-005 with labels 1–5."
    - paragraph: CubiCasa5K · CC BY-NC-SA · non-commercial use only. Extruded heights are generated for demo.
    - button "Visualise it"
  - region "3D viewer":
    - text: Storey
    - button "Previous storey": −
    - combobox "Storey":
      - option "All storeys"
      - option "Keller"
      - option "Erdgeschoss" [selected]
      - option "1. Obergeschoss"
      - option "2. Obergeschoss"
      - option "Dachgeschoss"
    - button "Next storey": +
    - checkbox "Show roof"
    - text: Show roof
    - button "Walk"
    - button "Edit"
    - button "Findings" [pressed]
    - button "Run checks"
    - text: violation suggestion info All storeys
    - 'button "1 suggestion finding: 3Zb0LaH4z9HPmaVjAzVngL"'
    - 'button "1 suggestion finding: 0xQhptVzf44Qzhs9jMEILa"'
    - 'button "1 suggestion finding: 0o_5lbt6jCpRs3V3FoLyNr"'
    - paragraph: Drag to orbit · Scroll to zoom · Click an item to identify it
    - status "Picked item": No item selected
```

# Test source

```ts
  1  | import { expect, test, type Page } from '@playwright/test';
  2  | import type { Viewer } from '../src/viewer3d/viewer';
  3  | import type { Finding } from '../src/viewer3d/findings';
  4  | 
  5  | test.use({
  6  |   reducedMotion: 'reduce',
  7  |   launchOptions: {
  8  |     executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
  9  |     args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
  10 |   },
  11 | });
  12 | test.setTimeout(60_000);
  13 | const docId = 'ifc_bench__ac20-arc';
  14 | const itemId = '0xQhptVzf44Qzhs9jMEILa';
  15 | const ruleId = 'fi-fire-exits-per-storey';
  16 | type TestWindow = typeof window & { __viewer3d: Viewer };
  17 | const pins = (page: Page) => page.evaluate(() => (window as TestWindow).__viewer3d.findings());
  18 | 
  19 | test('real AC20 checks pin the fire-exit finding above its item and show the sourced rule and tags', async ({ page, request }) => {
  20 |   await page.goto(`/?doc=${docId}&viewer3dTest=1#/viewer-test`);
  21 |   const viewer = page.getByRole('region', { name: '3D viewer', exact: true });
  22 |   await expect(viewer).toHaveAttribute('data-state', 'ready', { timeout: 30_000 });
  23 |   const toggle = viewer.getByRole('button', { name: 'Findings', exact: true });
  24 |   await expect(toggle).toHaveAttribute('aria-pressed', 'false');
  25 |   expect(await pins(page)).toEqual([]);
  26 |   const loaded = page.waitForResponse((response) => response.url().includes('/api/findings?doc_id=') && response.request().method() === 'GET');
  27 |   await toggle.click();
  28 |   expect((await loaded).ok()).toBe(true);
  29 |   await expect(viewer.getByLabel('Finding severity legend')).toHaveText('violationsuggestioninfo');
  30 |   const runButton = viewer.getByRole('button', { name: 'Run checks', exact: true });
  31 |   await expect(runButton).toBeEnabled();
  32 |   const ran = page.waitForResponse((response) => response.url().endsWith('/api/findings/run') && response.request().method() === 'POST');
  33 |   await runButton.click();
  34 |   const response = await ran;
  35 |   expect(response.ok()).toBe(true);
  36 |   const result = await response.json() as { status: string; findings: Finding[] };
  37 |   expect(result.status).toBe('ok');
  38 |   const finding = result.findings.find((entry) => entry.rule_id === ruleId && entry.item_ids[0] === itemId)!;
  39 |   expect(finding).toBeTruthy();
  40 |   expect(finding.rule.text).toBeTruthy();
  41 |   await expect.poll(async () => (await pins(page)).some((pin) => pin.id === finding.id)).toBe(true);
  42 | 
  43 |   const position = await page.evaluate((id) => {
  44 |     const viewer = (window as TestWindow).__viewer3d;
  45 |     const pin = viewer.findings().find((entry) => entry.item_id === id)!;
  46 |     const [min, max] = viewer.scene!.manifest.items[id].bbox_m!;
  47 |     const point = viewer.camera.position.clone().set((min[0] + max[0]) / 2, max[1], (min[2] + max[2]) / 2).project(viewer.camera);
  48 |     const rect = viewer.renderer.domElement.getBoundingClientRect();
  49 |     return { pin, top: [rect.left + (point.x + 1) * rect.width / 2, rect.top + (1 - point.y) * rect.height / 2] };
  50 |   }, itemId);
  51 |   expect(position.pin.screen_xy).not.toBeNull();
  52 |   expect(Math.abs(position.pin.screen_xy![0] - position.top[0])).toBeLessThan(3);
  53 |   expect(position.top[1] - position.pin.screen_xy![1]).toBeGreaterThan(20);
  54 |   expect(position.top[1] - position.pin.screen_xy![1]).toBeLessThan(32);
  55 |   await page.mouse.click(...position.pin.screen_xy!);
  56 |   const card = viewer.getByRole('complementary', { name: 'Finding details' });
> 57 |   await expect(card.getByRole('heading', { name: ruleId, exact: true })).toBeVisible();
     |                                                                          ^ Error: expect(locator).toBeVisible() failed
  58 |   await expect(card.locator('blockquote').filter({ hasText: finding.rule.text }).first()).toHaveText(finding.rule.text);
  59 |   if (finding.rule.source_title) await expect(card).toContainText(finding.rule.source_title);
  60 |   if (finding.message) await expect(card).toContainText(finding.message);
  61 |   await card.getByRole('button', { name: 'Show items', exact: true }).first().click();
  62 |   const state = await page.evaluate(() => (window as TestWindow).__viewer3d.getCommandState());
  63 |   expect(Object.keys(state.highlighted)).toEqual(expect.arrayContaining(finding.item_ids));
  64 |   const tag = await page.evaluate((id) => (window as TestWindow).__viewer3d.scene!.manifest.items[id].tag ?? id, itemId);
  65 |   expect(state.highlighted[itemId]).toBe(tag);
  66 | 
  67 |   // A second real run must refetch over findings.updated without pressing the UI action.
  68 |   const refreshed = page.waitForResponse((response) => response.url().includes('/api/findings?doc_id=') && response.request().method() === 'GET');
  69 |   const rerun = await request.post('/api/findings/run', { data: { doc_id: docId } });
  70 |   expect(rerun.ok()).toBe(true);
  71 |   const latest = (await rerun.json() as { findings: Finding[] }).findings;
  72 |   expect((await refreshed).ok()).toBe(true);
  73 |   await expect.poll(async () => (await pins(page)).map((pin) => pin.id).sort()).toEqual(latest.map((entry) => entry.id).sort());
  74 |   await toggle.click();
  75 |   expect(await pins(page)).toEqual([]);
  76 |   await expect(card).toHaveCount(0);
  77 |   const stored = page.waitForResponse((response) => response.url().includes('/api/findings?doc_id='));
  78 |   await toggle.click();
  79 |   expect((await stored).ok()).toBe(true);
  80 |   await expect.poll(async () => (await pins(page)).length).toBeGreaterThan(0);
  81 | });
  82 | 
```