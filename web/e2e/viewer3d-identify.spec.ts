import { expect, test, type Page } from '@playwright/test';
import type { Viewer } from '../src/viewer3d/viewer';
import type { SceneManifest } from '../src/viewer3d/scene';
import type { IFCElement } from '../src/viewer3d/identify';

test.use({
  launchOptions: {
    executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
    args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
  },
});

const docId = 'ifc_bench__ac20-arc';
const doorId = '3qloCPnZDEQBom1ZjBlwJP';

/** Move beside a known door to avoid walls occluding it, then project its bbox centre. */
async function projectDoorCentre(page: Page, item_id: string) {
  return page.evaluate((id) => {
    const viewer = (window as typeof window & { viewer3dTest?: Viewer }).viewer3dTest;
    if (!viewer?.scene) throw new Error('Dev viewer not ready');
    const item = viewer.scene.manifest.items[id];
    if (!item?.bbox_m || !viewer.scene.items.has(id)) throw new Error(`Missing door geometry: ${id}`);
    const [min, max] = item.bbox_m;
    const centre = viewer.camera.position.clone().set(
      (min[0] + max[0]) / 2, (min[1] + max[1]) / 2, (min[2] + max[2]) / 2,
    );
    viewer.controls.enableDamping = false;
    viewer.controls.minDistance = 0.01;
    viewer.camera.near = 0.005;
    viewer.camera.updateProjectionMatrix();
    viewer.controls.target.copy(centre);
    viewer.camera.position.copy(centre);
    // Stay within the opening: AC20 includes closed IfcSpace surfaces around rooms.
    const axis = max[0] - min[0] < max[2] - min[2] ? 'x' : 'z';
    viewer.camera.position[axis] += 0.08;
    viewer.controls.update();
    viewer.camera.updateMatrixWorld(true);
    const projected = centre.project(viewer.camera);
    const rect = viewer.renderer.domElement.getBoundingClientRect();
    return { x: rect.left + (projected.x + 1) / 2 * rect.width,
      y: rect.top + (1 - projected.y) / 2 * rect.height };
  }, item_id);
}

test('clicking an AC20 door identifies its name and storey; close and Escape dismiss it', async ({ page, request }) => {
  const response = await request.get(`/api/docs/${docId}/scene`);
  expect(response.ok(), 'AC20 scene must be served by the shared API').toBe(true);
  const manifest = await response.json() as SceneManifest;
  const door = manifest.items[doorId];
  expect(door.kind).toBe('door');

  // The SERVER endpoint is optional; fallback identity comes from the scene.
  const elementsResponse = await request.get(`/api/docs/${docId}/files/elements.json`);
  let element: IFCElement | undefined;
  if (elementsResponse.ok()) {
    const data = await elementsResponse.json() as IFCElement[] | { elements: IFCElement[] };
    element = (Array.isArray(data) ? data : data.elements).find((entry) => entry.item_id === doorId);
  }
  const expectedStorey = element?.storey ?? door.storey;
  const storey = typeof expectedStorey === 'string' ? expectedStorey : expectedStorey?.name;
  expect(storey).toBeTruthy();

  await page.goto('/#/viewer-test');
  await page.getByRole('combobox', { name: 'Document', exact: true }).selectOption(docId);
  const viewer = page.getByRole('region', { name: '3D viewer', exact: true });
  await expect(viewer).toHaveAttribute('data-state', 'ready');
  await expect.poll(() => page.evaluate(() =>
    (window as typeof window & { viewer3dTest?: Viewer }).viewer3dTest?.scene?.manifest.doc_id,
  )).toBe(docId);
  await viewer.getByRole('combobox', { name: 'Storey', exact: true }).selectOption(storey!);
  const point = await projectDoorCentre(page, doorId);
  await page.mouse.click(point.x, point.y);
  const card = viewer.getByRole('complementary', { name: 'Item details', exact: true });
  await expect(card).toHaveAttribute('data-item-id', doorId);
  await expect(card.getByRole('heading')).toHaveText(element?.name || doorId);
  await expect(card.locator('dl > div').filter({ has: page.locator('dt', { hasText: /^Storey$/ }) }).locator('dd'))
    .toHaveText(storey!);
  await expect(card.locator('dl > div').filter({ has: page.locator('dt', { hasText: /^Kind$/ }) }).locator('dd'))
    .toHaveText('door');

  await card.getByRole('button', { name: 'Close item details', exact: true }).click();
  await expect(card).toHaveCount(0);
  await page.mouse.click(point.x, point.y);
  await expect(card).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(card).toHaveCount(0);
  await page.mouse.click(point.x, point.y);
  await expect(card).toBeVisible();
  await page.getByRole('combobox', { name: 'Document', exact: true }).selectOption('digital_hub');
  await expect(card).toHaveCount(0);
  await expect(viewer).toHaveAttribute('data-state', 'ready');
});
