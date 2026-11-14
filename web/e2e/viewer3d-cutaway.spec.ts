import { expect, test, type Page } from '@playwright/test';
import type { Viewer } from '../src/viewer3d/viewer';
import type { SceneManifest } from '../src/viewer3d/scene';
import { indexElements } from '../src/viewer3d/identify';
import { cutawayStoreys, isRoof } from '../src/viewer3d/cutaway';

test.use({
  reducedMotion: 'reduce',
  launchOptions: {
    executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
    args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
  },
});
test.setTimeout(60_000);
const docId = 'ifc_bench__ac20-arc';
type TestWindow = typeof window & { viewer3dTest: Viewer; visualise3dTest: Viewer };
const state = (page: Page) => page.evaluate(() => (window as TestWindow).viewer3dTest.getCutawayState());

async function visibility(page: Page, ids: string[], panel = false) {
  return page.evaluate(({ ids, panel }) => {
    const viewer = (window as TestWindow)[panel ? 'visualise3dTest' : 'viewer3dTest'];
    return ids.map((id) => {
      const object = viewer.scene!.items.get(id);
      if (!object) throw new Error(`Missing rendered geometry: ${id}`);
      for (let current: typeof object | null = object; current; current = current.parent) {
        if (!current.visible) return false;
      }
      return true;
    });
  }, { ids, panel });
}

test('AC20 opens as a roofless ground cutaway; roof toggle, stepper, highlights, and VisualisePanel follow the policy', async ({ page, request }) => {
  const response = await request.get(`/api/docs/${docId}/scene`);
  expect(response.ok()).toBe(true);
  const manifest = await response.json() as SceneManifest;
  const elementsResponse = await request.get(`/api/docs/${docId}/files/elements.json`);
  expect(elementsResponse.ok(), 'AC20 roof slabs need the IFC metadata').toBe(true);
  const elements = indexElements(await elementsResponse.json());
  const storeys = cutawayStoreys(manifest);
  const ground = storeys.find((storey) => storey.elevation_m !== undefined && storey.elevation_m >= 0)!;
  const groundIndex = storeys.indexOf(ground);
  const upper = storeys[groundIndex + 1];
  const roofIds = Object.entries(manifest.items).filter(([id, item]) => isRoof(item.kind, elements.get(id))).map(([id]) => id);
  const roofSlabIds = roofIds.filter((id) => elements.get(id)?.ifc_class === 'IfcSlab'
    && elements.get(id)?.predefined_type === 'ROOF');
  expect(roofSlabIds).toHaveLength(21);
  expect(roofIds.length).toBeGreaterThan(0);
  await page.goto(`/?doc=${docId}#/viewer-test`);
  const viewer = page.getByRole('region', { name: '3D viewer', exact: true });
  await expect(viewer).toHaveAttribute('data-state', 'ready', { timeout: 30_000 });
  await expect.poll(() => state(page)).toMatchObject({ activeStorey: ground.name, showRoof: false });
  const resolved = await page.evaluate(() => [...(window as TestWindow).viewer3dTest.scene!.items.keys()]);
  const roofs = roofIds.filter((id) => resolved.includes(id));
  expect(roofs).toEqual(expect.arrayContaining(roofSlabIds));
  expect(roofs.length).toBeGreaterThan(0);
  expect(await visibility(page, roofs)).toEqual(roofs.map(() => false));
  const above = resolved.filter((id) => {
    const storey = manifest.items[id].storey;
    const name = typeof storey === 'string' ? storey : storey?.name;
    return storeys.findIndex((entry) => entry.name === name) > groundIndex;
  });
  expect(above.length).toBeGreaterThan(0);
  expect(await visibility(page, above)).toEqual(above.map(() => false));
  const initial = await state(page);
  const roofToggle = viewer.getByRole('checkbox', { name: 'Show roof', exact: true });
  await roofToggle.check();
  expect(await visibility(page, roofs)).toEqual(roofs.map(() => true));
  expect((await state(page)).hiddenCount).toBeLessThan(initial.hiddenCount);
  await roofToggle.uncheck();
  await viewer.getByRole('button', { name: 'Next storey', exact: true }).click();
  expect((await state(page)).activeStorey).toBe(upper.name);
  expect((await state(page)).hiddenCount).toBeLessThan(initial.hiddenCount);
  await viewer.getByRole('button', { name: 'Previous storey', exact: true }).click();
  expect(await state(page)).toEqual(initial);

  const upperId = above.find((id) => !roofIds.includes(id) && (() => {
    const storey = manifest.items[id].storey;
    return (typeof storey === 'string' ? storey : storey?.name) === upper.name;
  })())!;
  expect(upperId).toBeTruthy();
  await page.evaluate((id) => (window as TestWindow).viewer3dTest.highlight([id], { labels: { [id]: '12' } }), upperId);
  await expect(viewer.getByRole('combobox', { name: 'Storey', exact: true })).toHaveValue(upper.name);
  expect(await visibility(page, [upperId])).toEqual([true]);
  await expect(viewer.getByLabel(`Item 12: ${upperId}`, { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Clear highlight', exact: true }).click();

  await page.getByLabel('Visualise document ID', { exact: true }).fill(docId);
  await page.getByRole('button', { name: 'Visualise it', exact: true }).click();
  const panel = page.getByRole('dialog', { name: 'Visualise it', exact: true });
  await expect(panel.getByRole('region', { name: '3D viewer', exact: true })).toHaveAttribute('data-state', 'ready', { timeout: 30_000 });
  await expect.poll(() => page.evaluate(() => (window as TestWindow).visualise3dTest?.getCutawayState()))
    .toMatchObject({ activeStorey: ground.name, showRoof: false });
  expect(await visibility(page, roofs, true)).toEqual(roofs.map(() => false));
  await panel.getByRole('checkbox', { name: 'Show roof', exact: true }).check();
  expect(await visibility(page, roofs, true)).toEqual(roofs.map(() => true));
  await panel.getByRole('checkbox', { name: 'Show roof', exact: true }).uncheck();
  // The shared live channel must move an already-open panel to a newly selected storey.
  await page.evaluate((id) => (window as TestWindow).viewer3dTest.highlight([id], { labels: { [id]: '19' } }), upperId);
  await expect.poll(() => page.evaluate(() => (window as TestWindow).visualise3dTest.getCutawayState().activeStorey))
    .toBe(upper.name);
  await expect.poll(() => page.evaluate(() => (window as TestWindow).visualise3dTest.getHighlightState()))
    .toMatchObject({ highlighted: [upperId], labels: { [upperId]: '19' } });
  expect(await visibility(page, [upperId], true)).toEqual([true]);
  await expect(panel.getByLabel(`Item 19: ${upperId}`, { exact: true })).toBeVisible();
});

test('light extruded plan has no roof control and keeps highlighted items visible', async ({ page }) => {
  await page.goto('/?doc=colorful-11397#/viewer-test');
  const viewer = page.getByRole('region', { name: '3D viewer', exact: true });
  await expect(viewer).toHaveAttribute('data-state', 'ready', { timeout: 30_000 });
  await expect(viewer.getByRole('checkbox', { name: 'Show roof', exact: true })).toHaveCount(0);
  expect((await state(page)).hiddenCount).toBe(0);
  await page.getByRole('button', { name: 'Highlight 3 random items', exact: true }).click();
  const ids = await page.evaluate(() => (window as TestWindow).viewer3dTest.getHighlightState().highlighted);
  expect(await visibility(page, ids)).toEqual([true, true, true]);

  await page.getByRole('button', { name: 'Visualise it', exact: true }).click();
  const panel = page.getByRole('dialog', { name: 'Visualise it', exact: true });
  await expect(panel.getByRole('region', { name: '3D viewer', exact: true })).toHaveAttribute('data-state', 'ready');
  // Each source selection rerenders the parent with a new, equivalent answer.
  // The panel must retain the live selection rather than reapply that answer.
  const id = 'window-006';
  for (const label of ['19', '12']) {
    await page.evaluate(({ id, label }) => (window as TestWindow).viewer3dTest.highlight([id], { labels: { [id]: label } }), { id, label });
    await expect.poll(() => page.evaluate(() => (window as TestWindow).visualise3dTest.getHighlightState()))
      .toMatchObject({ highlighted: [id], labels: { [id]: label } });
    await expect(panel.getByLabel(`Item ${label}: ${id}`, { exact: true })).toBeVisible();
  }
  await page.evaluate(() => (window as TestWindow).viewer3dTest.clearHighlight());
  await expect(panel.locator('.viewer3d-item-label')).toHaveCount(0);
});
