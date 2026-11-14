import { expect, test, type Page } from '@playwright/test';
import type { Viewer } from '../src/viewer3d/viewer';
import type { Finding } from '../src/viewer3d/findings';

test.use({
  reducedMotion: 'reduce',
  launchOptions: {
    executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
    args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
  },
});
test.setTimeout(60_000);
const docId = 'ifc_bench__ac20-arc';
const itemId = '0xQhptVzf44Qzhs9jMEILa';
const ruleId = 'fi-fire-exits-per-storey';
type TestWindow = typeof window & { __viewer3d: Viewer };
const pins = (page: Page) => page.evaluate(() => (window as TestWindow).__viewer3d.findings());

test('real AC20 checks pin the fire-exit finding above its item and show the sourced rule and tags', async ({ page, request }) => {
  await page.goto(`/?doc=${docId}&viewer3dTest=1#/viewer-test`);
  const viewer = page.getByRole('region', { name: '3D viewer', exact: true });
  await expect(viewer).toHaveAttribute('data-state', 'ready', { timeout: 30_000 });
  const toggle = viewer.getByRole('button', { name: 'Findings', exact: true });
  await expect(toggle).toHaveAttribute('aria-pressed', 'false');
  expect(await pins(page)).toEqual([]);
  const loaded = page.waitForResponse((response) => response.url().includes('/api/findings?doc_id=') && response.request().method() === 'GET');
  await toggle.click();
  expect((await loaded).ok()).toBe(true);
  await expect(viewer.getByLabel('Finding severity legend')).toHaveText('violationsuggestioninfo');
  const runButton = viewer.getByRole('button', { name: 'Run checks', exact: true });
  await expect(runButton).toBeEnabled();
  const ran = page.waitForResponse((response) => response.url().endsWith('/api/findings/run') && response.request().method() === 'POST');
  await runButton.click();
  const response = await ran;
  expect(response.ok()).toBe(true);
  const result = await response.json() as { status: string; findings: Finding[] };
  expect(result.status).toBe('ok');
  const finding = result.findings.find((entry) => entry.rule_id === ruleId && entry.item_ids[0] === itemId)!;
  expect(finding).toBeTruthy();
  expect(finding.rule.text).toBeTruthy();
  await expect.poll(async () => (await pins(page)).some((pin) => pin.id === finding.id)).toBe(true);

  const position = await page.evaluate((id) => {
    const viewer = (window as TestWindow).__viewer3d;
    const pin = viewer.findings().find((entry) => entry.item_id === id)!;
    const [min, max] = viewer.scene!.manifest.items[id].bbox_m!;
    const point = viewer.camera.position.clone().set((min[0] + max[0]) / 2, max[1], (min[2] + max[2]) / 2).project(viewer.camera);
    const rect = viewer.renderer.domElement.getBoundingClientRect();
    return { pin, top: [rect.left + (point.x + 1) * rect.width / 2, rect.top + (1 - point.y) * rect.height / 2] };
  }, itemId);
  expect(position.pin.screen_xy).not.toBeNull();
  expect(Math.abs(position.pin.screen_xy![0] - position.top[0])).toBeLessThan(3);
  expect(position.top[1] - position.pin.screen_xy![1]).toBeGreaterThan(20);
  expect(position.top[1] - position.pin.screen_xy![1]).toBeLessThan(32);
  // Exercise the actual canvas raycast, independently of the accessible DOM
  // buttons over the sprites. Only their pointer hit targets are disabled.
  const pinButtons = viewer.locator('.viewer3d-finding-pin');
  await pinButtons.evaluateAll((buttons) => buttons.forEach((button) => { (button as HTMLElement).style.pointerEvents = 'none'; }));
  expect(await page.evaluate(([x, y]) => document.elementFromPoint(x, y)?.tagName, position.pin.screen_xy!)).toBe('CANVAS');
  await page.mouse.click(...position.pin.screen_xy!);
  const card = viewer.getByRole('complementary', { name: 'Finding details' });
  await expect(card.getByRole('heading', { name: ruleId, exact: true })).toBeVisible();
  await expect(card.locator('blockquote').filter({ hasText: finding.rule.text }).first()).toHaveText(finding.rule.text);
  if (finding.rule.source_title) await expect(card).toContainText(finding.rule.source_title);
  if (finding.message) await expect(card).toContainText(finding.message);
  await card.getByRole('button', { name: 'Show items', exact: true }).first().click();
  const state = await page.evaluate(() => (window as TestWindow).__viewer3d.getCommandState());
  expect(Object.keys(state.highlighted)).toEqual(expect.arrayContaining(finding.item_ids));
  const tag = await page.evaluate((id) => (window as TestWindow).__viewer3d.scene!.manifest.items[id].tag ?? id, itemId);
  expect(state.highlighted[itemId]).toBe(tag);

  await card.getByRole('button', { name: 'Close findings', exact: true }).click();
  await expect(card).toHaveCount(0);
  await pinButtons.evaluateAll((buttons) => buttons.forEach((button) => { (button as HTMLElement).style.removeProperty('pointer-events'); }));
  // The same pin must also open through its keyboard-accessible button.
  const pinButton = viewer.getByRole('button', { name: `1 suggestion finding: ${itemId}`, exact: true });
  await pinButton.focus();
  await pinButton.press('Enter');
  await expect(card.getByRole('heading', { name: ruleId, exact: true })).toBeVisible();

  // A second real run must refetch over findings.updated without pressing the UI action.
  const refreshed = page.waitForResponse((response) => response.url().includes('/api/findings?doc_id=') && response.request().method() === 'GET');
  const rerun = await request.post('/api/findings/run', { data: { doc_id: docId } });
  expect(rerun.ok()).toBe(true);
  const latest = (await rerun.json() as { findings: Finding[] }).findings;
  expect((await refreshed).ok()).toBe(true);
  await expect.poll(async () => (await pins(page)).map((pin) => pin.id).sort()).toEqual(latest.map((entry) => entry.id).sort());
  await toggle.click();
  expect(await pins(page)).toEqual([]);
  await expect(card).toHaveCount(0);
  const stored = page.waitForResponse((response) => response.url().includes('/api/findings?doc_id='));
  await toggle.click();
  expect((await stored).ok()).toBe(true);
  await expect.poll(async () => (await pins(page)).length).toBeGreaterThan(0);
});
