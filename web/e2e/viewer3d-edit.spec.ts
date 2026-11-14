import { expect, test, type Page } from '@playwright/test';
import type { Viewer } from '../src/viewer3d/viewer';
import type { LinkedViewerCanvas } from '../src/viewer3d/Viewer3D';
import type { AdvisorCard } from '../src/viewer3d/advisor';

test.use({ launchOptions: {
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
} });
const docId = 'ifc_bench__ac20-arc';
const doorId = '3qloCPnZDEQBom1ZjBlwJP';
type TestWindow = Window & typeof globalThis & { __viewer3d: Viewer };

async function open(page: Page) {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto(`/?doc=${docId}&viewer3dTest=1#/viewer-test`);
  const viewer = page.getByRole('region', { name: '3D viewer', exact: true });
  await expect(viewer).toHaveAttribute('data-state', 'ready');
  await expect.poll(() => page.evaluate(() => (window as TestWindow).__viewer3d?.scene?.manifest.doc_id)).toBe(docId);
  await viewer.getByRole('button', { name: 'Edit', exact: true }).click();
  return viewer;
}

async function select(page: Page, id: string) {
  // Same selection path as canvas picks; raycast identification is covered by T-02.
  const selected = await page.getByLabel('3D building model', { exact: true }).evaluate((canvas, id) =>
    (canvas as LinkedViewerCanvas).__viewer3d!.pick(id), id);
  expect(selected).toBe(true);
}
const hidden = (page: Page) => page.evaluate(() => (window as TestWindow).__viewer3d.getCommandState().hidden);

// advisor-fixture is generated for demo. Only this advisor response is stubbed;
// the scene, source item IDs, geometry, commands and remaining API calls are real.
function advisorFixture(ids: string[]) {
  const base: AdvisorCard = { card_id: 'advisor-fixture-door', kind: 'warning', title: 'Door edit — generated for demo',
    body: 'Inspect the selected opening before keeping this change. Generated for demo.', item_ids: ids,
    source: { type: 'document', ref: 'advisor-fixture', title: 'Door source — generated for demo', quote: 'This door source was generated for demo.' } };
  return { cards: [base,
    { ...base, card_id: 'advisor-fixture-option', kind: 'option', title: 'Opening option — generated for demo',
      source: { ...base.source, title: 'Option source — generated for demo', quote: 'This option source was generated for demo.' } },
    { ...base, card_id: 'advisor-fixture-unsourced', title: 'Unsourced claim must be absent', source: undefined },
  ] };
}

test('AC20 remove requests advice, renders only sourced advisor-fixture cards, highlights tags and undoes removal', async ({ page }) => {
  const viewer = await open(page);
  const sourceItem = await page.evaluate((id) => (window as TestWindow).__viewer3d.scene!.manifest.items[id], doorId);
  expect(sourceItem.kind).toBe('door');
  const storey = typeof sourceItem.storey === 'string' ? sourceItem.storey : sourceItem.storey?.name;
  await viewer.getByRole('combobox', { name: 'Storey', exact: true }).selectOption(storey!);
  const targetId = await page.evaluate((removed) => {
    const viewer = (window as TestWindow).__viewer3d;
    return [...viewer.scene!.items.keys()].find((id) => id !== removed && viewer.scene!.manifest.items[id].kind === 'door')!;
  }, doorId);
  await page.route('**/api/advise', async (route) => {
    const payload = route.request().postDataJSON();
    expect(payload.doc_id).toBe(docId);
    expect(payload.edit).toMatchObject({ op: 'hide', item_ids: [doorId] });
    await route.fulfill({ json: advisorFixture([targetId]) });
  }, { times: 1 });
  await select(page, doorId);
  const requestPromise = page.waitForRequest((request) => request.url().endsWith('/api/advise') && request.method() === 'POST');
  await viewer.getByRole('button', { name: 'Remove', exact: true }).click();
  const request = await requestPromise;
  expect(request.postDataJSON()).toMatchObject({ doc_id: docId, edit: { op: 'hide', item_ids: [doorId] } });
  await expect.poll(() => hidden(page)).toContain(doorId);
  await expect(viewer.locator('[data-advisor-card]')).toHaveCount(2);
  await expect(viewer.getByText('Door source — generated for demo', { exact: true })).toBeVisible();
  await expect(viewer.getByText('Option source — generated for demo', { exact: true })).toBeVisible();
  await expect(viewer.getByText('Unsourced claim must be absent')).toHaveCount(0);
  await viewer.getByText('Door source — generated for demo', { exact: true }).click();
  await expect(viewer.getByText('This door source was generated for demo.', { exact: true })).toBeVisible();
  await viewer.getByRole('button', { name: 'Highlight: Door edit — generated for demo', exact: true }).click();
  await expect.poll(() => page.evaluate((id) => (window as TestWindow).__viewer3d.getCommandState().highlighted[id], targetId))
    .toBe(await page.evaluate((id) => (window as TestWindow).__viewer3d.scene!.manifest.items[id].tag ?? id, targetId));
  await viewer.getByRole('button', { name: 'Undo', exact: true }).click();
  await expect.poll(() => hidden(page)).not.toContain(doorId);
  // Return to the door's storey after the advisor highlighted another opening.
  await viewer.getByRole('combobox', { name: 'Storey', exact: true }).selectOption(storey!);
  await expect.poll(() => page.evaluate((id) => (window as TestWindow).__viewer3d.scene!.items.get(id)!.visible, doorId)).toBe(true);
});

test('AC20 edit renders the real advisor API cards or its honest empty state without stubs', async ({ page }) => {
  const viewer = await open(page);
  await select(page, doorId);
  const responsePromise = page.waitForResponse((response) => response.url().endsWith('/api/advise')
    && response.request().method() === 'POST' && response.request().postDataJSON()?.edit?.op === 'hide');
  await viewer.getByRole('button', { name: 'Remove', exact: true }).click();
  const response = await responsePromise;
  expect(response.ok(), 'Real /api/advise must accept the AC20 hide edit').toBe(true);
  const result = await response.json() as { cards: AdvisorCard[] };
  if (!result.cards.length) await expect(viewer.getByText('No advice for this change.', { exact: true })).toBeVisible();
  else {
    const cards = result.cards.filter((card) => card.source).slice(0, 3);
    await expect(viewer.locator('[data-advisor-card]')).toHaveCount(cards.length);
    // Cards show a short rule reference; the full source title is the summary's title (AdvisorCardView).
    for (const card of cards) await expect(viewer.getByTitle(card.source.title, { exact: true }).first()).toBeVisible();
  }
  await viewer.getByRole('button', { name: 'Undo', exact: true }).click();
  await expect.poll(() => hidden(page)).not.toContain(doorId);
});

test('wall materials and snapped floor dragging stay local and reset together', async ({ page }) => {
  const sent: { op: string; offset_m: number[]; material?: string | null }[] = [];
  page.on('websocket', (socket) => socket.on('framesent', ({ payload }) => {
    try { const e = JSON.parse(String(payload)); if (e.type === 'scene.edit' && (e.op === 'move' || e.op === 'material')) sent.push(e); } catch { /* not JSON */ }
  }));
  const viewer = await open(page);
  const id = await page.evaluate(() => {
    const viewer = (window as TestWindow).__viewer3d;
    return [...viewer.scene!.items.keys()].find((id) => viewer.scene!.manifest.items[id].kind === 'wall')!;
  });
  const before = await page.evaluate((id) => {
    const viewer = (window as TestWindow).__viewer3d;
    return { manifest: JSON.stringify(viewer.scene!.manifest), position: viewer.scene!.items.get(id)!.position.toArray() };
  }, id);
  await select(page, id);
  const materialRequest = page.waitForRequest((request) => request.url().endsWith('/api/advise') && request.postDataJSON()?.edit?.op === 'material');
  await viewer.getByRole('combobox', { name: 'Change material', exact: true }).selectOption('Timber frame');
  expect((await materialRequest).postDataJSON().edit).toMatchObject({ item_ids: [id], detail: { material: 'Timber frame' } });
  await expect(viewer.getByText('Material: Timber frame', { exact: true })).toBeVisible();
  await viewer.getByRole('button', { name: 'Move', exact: true }).click();
  const canvas = viewer.getByLabel('3D building model', { exact: true });
  const box = (await canvas.boundingBox())!;
  const moveRequest = page.waitForRequest((request) => request.url().endsWith('/api/advise') && request.postDataJSON()?.edit?.op === 'move');
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 65, box.y + box.height / 2 + 20, { steps: 5 });
  await page.mouse.up();
  const payload = (await moveRequest).postDataJSON();
  expect(payload.edit.item_ids).toEqual([id]);
  const delta = payload.edit.detail.delta_m as number[];
  expect(delta.some((value) => value !== 0)).toBe(true);
  for (const value of delta) expect(value * 10).toBeCloseTo(Math.round(value * 10));
  const resetRequest = page.waitForRequest((request) => request.url().endsWith('/api/advise') && request.postDataJSON()?.edit?.op === 'reset');
  await viewer.getByRole('button', { name: 'Reset edits', exact: true }).click();
  await resetRequest;
  expect(await page.evaluate((id) => {
    const viewer = (window as TestWindow).__viewer3d;
    return { manifest: JSON.stringify(viewer.scene!.manifest), position: viewer.scene!.items.get(id)!.position.toArray(), edits: viewer.getEditState() };
  }, id)).toEqual({ ...before, edits: { undoCount: 0, moved: {}, moveDelta: {}, materials: {} } });
  // Shared chat edit layer: the material change, the move and the reset went out as scene.edit commands.
  await expect.poll(() => sent.map((e) => [e.op, e.op === 'move' ? Math.abs(e.offset_m[0]) + Math.abs(e.offset_m[1]) > 0 : e.material ?? null]))
    .toEqual([['material', 'Timber frame'], ['move', true], ['move', false], ['material', null]]);
});
