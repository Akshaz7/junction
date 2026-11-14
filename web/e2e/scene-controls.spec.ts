import { expect, test } from '@playwright/test';
import type { Viewer } from '../src/viewer3d/viewer';

type TestWindow = typeof window & { viewer3dTest: Viewer };

test('Shift-click selects a kind; Clear highlights preserves a removal; Undo restores it', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  // Offline geometry and isolated live transport: this check needs no API or shared chat.
  await page.routeWebSocket('**/ws*', () => {});
  await page.route('**/api/advise', (route) => route.fulfill({ json: { cards: [] } }));
  await page.goto('/?doc=colorful-11397&viewer3dTest=1#/viewer-test');
  const viewer = page.getByRole('region', { name: '3D viewer', exact: true });
  await expect(viewer).toHaveAttribute('data-state', 'ready');
  const target = await page.evaluate(() => {
    const viewer = (window as TestWindow).viewer3dTest;
    const canvas = viewer.renderer.domElement;
    const rect = canvas.getBoundingClientRect();
    for (const id of viewer.scene!.items.keys()) {
      const point = viewer.itemScreenPosition(id);
      if (!point?.visible || viewer.pick(rect.left + point.x, rect.top + point.y) !== id) continue;
      const kind = viewer.scene!.manifest.items[id].kind;
      return { id, x: rect.left + point.x, y: rect.top + point.y,
        expected: Object.keys(viewer.scene!.manifest.items).filter((key) => viewer.scene!.manifest.items[key].kind === kind) };
    }
    throw new Error('No visible item can be picked');
  });
  await page.keyboard.down('Shift');
  await page.mouse.click(target.x, target.y);
  await page.keyboard.up('Shift');
  await expect.poll(() => page.evaluate(() => (window as TestWindow).viewer3dTest.getHighlightState().highlighted.sort()))
    .toEqual([...target.expected].sort());
  await viewer.getByRole('button', { name: 'Edit', exact: true }).click();
  await viewer.getByRole('button', { name: 'Remove', exact: true }).click();
  await expect.poll(() => page.evaluate(() => (window as TestWindow).viewer3dTest.getCommandState().hidden)).toEqual([target.id]);
  await viewer.getByRole('button', { name: 'Clear highlights', exact: true }).click();
  await expect(viewer).toHaveAttribute('data-highlighted-item-ids', '[]');
  expect(await page.evaluate(() => (window as TestWindow).viewer3dTest.getCommandState().hidden)).toEqual([target.id]);
  await viewer.getByRole('button', { name: 'Undo', exact: true }).click();
  await expect.poll(() => page.evaluate(() => (window as TestWindow).viewer3dTest.getCommandState().hidden)).toEqual([]);
});
