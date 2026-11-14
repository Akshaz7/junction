import { expect, test, type Page } from '@playwright/test';
import type { Viewer } from '../src/viewer3d/viewer';
import type { SceneManifest } from '../src/viewer3d/scene';
import type { SceneCommand, SceneSnapshot } from '../src/viewer3d/commands';

test.use({
  actionTimeout: 15_000,
  launchOptions: {
    executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
    args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
  },
});
test.setTimeout(60_000);

type TestWindow = typeof window & { __viewer3d: Viewer; commandSockets: WebSocket[] };

async function ready(page: Page, api = false) {
  // The source geometry is unchanged. Tags are fixture metadata, generated for demo.
  await page.route(api ? '**/api/docs/ifc_bench__ac20-arc/scene' : '**/fixtures/colorful-11397/scene.json', async (route) => {
    const response = await route.fetch();
    const manifest = await response.json() as SceneManifest;
    let index = 0;
    for (const item of Object.values(manifest.items)) if (item.kind === 'window') item.tag = `W${++index}`;
    await route.fulfill({ response, json: manifest });
  });
  await page.addInitScript(() => {
    const sockets: WebSocket[] = [];
    Object.assign(window, { commandSockets: sockets });
    window.WebSocket = class extends WebSocket {
      constructor(url: string | URL, protocols?: string | string[]) {
        super(url, protocols);
        if (new URL(this.url).pathname === '/ws') sockets.push(this);
      }
    };
  });
  await page.goto(`/?viewer3dTest=1&doc=${api ? 'ifc_bench__ac20-arc' : 'colorful-11397'}#/viewer-test`);
  await expect(page.getByRole('region', { name: '3D viewer', exact: true }))
    .toHaveAttribute('data-state', 'ready', { timeout: 30_000 });
  await expect.poll(() => page.evaluate(() => Boolean((window as TestWindow).__viewer3d))).toBe(true);
}

const command = (page: Page, cmd: SceneCommand) => page.evaluate((cmd) => (window as TestWindow).__viewer3d.applyCommand(cmd), cmd);
const state = (page: Page) => page.evaluate(() => (window as TestWindow).__viewer3d.getCommandState());
const visible = (page: Page, id: string) => page.evaluate((id) => (window as TestWindow).__viewer3d.scene!.items.get(id)!.visible, id);

test('answer commands tag windows; real /ws hides W3 in a second context within 2 s and restores it', async ({ browser, baseURL }) => {
  const a = await browser.newContext({ baseURL, reducedMotion: 'reduce' });
  const b = await browser.newContext({ baseURL, reducedMotion: 'reduce' });
  try {
    const pageA = await a.newPage(); const pageB = await b.newPage();
    await ready(pageA); await ready(pageB);
    for (const page of [pageA, pageB]) await expect.poll(() => page.evaluate(() =>
      (window as TestWindow).commandSockets.at(-1)?.readyState === WebSocket.OPEN), { timeout: 9000 }).toBe(true);
    await pageA.getByRole('button', { name: 'Highlight all windows', exact: true }).click();
    const expected = await state(pageA);
    const ids = Object.keys(expected.highlighted);
    expect(ids.length).toBeGreaterThanOrEqual(3);
    const third = ids.find((id) => expected.highlighted[id] === 'W3')!;
    expect(third).toBeTruthy();
    await expect.poll(() => state(pageB), { timeout: 2000, intervals: [50, 100] }).toEqual(expected);
    for (const page of [pageA, pageB]) {
      await expect(page.locator('.viewer3d-item-label')).toHaveCount(ids.length);
      for (const [id, label] of Object.entries(expected.highlighted)) {
        await expect(page.getByLabel(`Item ${label}: ${id}`, { exact: true })).toBeVisible();
      }
    }
    await pageA.getByRole('button', { name: 'Hide W3', exact: true }).click();
    await expect.poll(() => state(pageB), { timeout: 2000, intervals: [50, 100] })
      .toEqual({ ...expected, hidden: [third], highlighted: Object.fromEntries(Object.entries(expected.highlighted).filter(([id]) => id !== third)) });
    for (const page of [pageA, pageB]) {
      expect(await visible(page, third)).toBe(false);
      await expect(page.getByLabel(`Item W3: ${third}`, { exact: true })).toHaveCount(0);
    }
    await pageB.getByRole('button', { name: 'Restore W3', exact: true }).click();
    await expect.poll(() => state(pageA), { timeout: 2000, intervals: [50, 100] }).toMatchObject({ hidden: [] });
    for (const page of [pageA, pageB]) expect(await visible(page, third)).toBe(true);
  } finally { await Promise.allSettled([a.close(), b.close()]); }
});

test('AC20 uses the same tags, command labels, isolate/reset, snapshot replacement and interrupted fades', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await ready(page, true);
  await page.getByRole('button', { name: 'Highlight all windows', exact: true }).click();
  const tagged = await state(page);
  const id = Object.keys(tagged.highlighted).find((id) => tagged.highlighted[id] === 'W3')!;
  expect(id).toBeTruthy();
  await command(page, { op: 'isolate', item_ids: [id], labels: { [id]: 'Opening W3' } });
  await expect(page.getByLabel(`Item Opening W3: ${id}`, { exact: true })).toBeVisible();
  expect((await state(page)).isolated).toEqual([id]);
  // Scene commands use manifest node mappings, not a plan-map ID naming assumption.
  await page.locator('canvas').evaluate((canvas, id) => {
    (canvas as HTMLCanvasElement & { __viewer3d: { pick(id: string): boolean } }).__viewer3d.pick(id);
  }, id);
  const card = page.getByRole('complementary', { name: 'Item details', exact: true });
  await expect(card.locator('dl > div').filter({ has: page.locator('dt', { hasText: /^Tag$/ }) }).locator('dd')).toHaveText('W3');
  await card.getByRole('button', { name: 'Close item details', exact: true }).click();
  await command(page, { op: 'reset', item_ids: [] });
  expect(await state(page)).toEqual({ hidden: [], highlighted: {}, isolated: null });

  // A late-join snapshot replaces isolation and restores from a later snapshot.
  const snapshot: SceneSnapshot = { hidden: [id], highlighted: [], labels: {} };
  await page.evaluate((snapshot) => (window as TestWindow).__viewer3d.applyState(snapshot), snapshot);
  expect(await visible(page, id)).toBe(false);
  await page.evaluate(() => (window as TestWindow).__viewer3d.applyState({ hidden: [], highlighted: [], labels: {} }));
  expect(await visible(page, id)).toBe(true);

  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await command(page, { op: 'hide', item_ids: [id] });
  // Restore before fade-out completes: the old fade must not disable the item later.
  await command(page, { op: 'restore', item_ids: [id] });
  await expect.poll(() => page.evaluate((id) => {
    const viewer = (window as TestWindow).__viewer3d;
    const object = viewer.scene!.items.get(id)!;
    return object.visible && !viewer.getCommandState().hidden.includes(id);
  }, id)).toBe(true);
  await command(page, { op: 'hide', item_ids: [id] });
  await expect.poll(() => visible(page, id)).toBe(false);
  await command(page, { op: 'restore', item_ids: [id] });
  await expect.poll(() => visible(page, id)).toBe(true);
});
