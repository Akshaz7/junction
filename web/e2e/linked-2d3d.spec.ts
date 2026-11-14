import { expect, test } from '@playwright/test';
import type { LinkedViewerCanvas } from '../src/viewer3d/Viewer3D';

test.use({
  viewport: { width: 1440, height: 1000 },
  reducedMotion: 'reduce',
  actionTimeout: 15_000,
  launchOptions: {
    executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
    args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
  },
});
test.setTimeout(60_000);

test('citation box 3 and a 3D pick select the same contract item in both visible panels', async ({ page }) => {
  await page.goto('/?viewer3dTest=1#/chat');
  await expect(page.getByText('Connected workspace', { exact: true })).toBeVisible();
  const composer = page.getByRole('combobox', { name: 'Ask about your drawings' });
  await composer.fill('@colorful-11397');
  await page.getByRole('option').filter({ hasText: 'colorful-11397' }).click();
  await composer.fill('How many windows are there?');
  await page.getByRole('button', { name: 'Send question', exact: true }).click();
  await page.locator('.answer-text').getByRole('button', { name: 'Open citation 1', exact: true }).click();

  const drawing = page.getByRole('region', { name: 'Drawing viewer', exact: true });
  const box3 = drawing.getByTestId('evidence-box-3');
  await expect(box3).toBeVisible();
  const itemId = await box3.getAttribute('data-item-id');
  expect(itemId, 'Each 2D box must expose its contract item_id').toBeTruthy();
  await drawing.getByRole('button', { name: 'Visualise it', exact: true }).click();
  const panel = page.getByRole('dialog', { name: 'Visualise it', exact: true });
  const viewer = panel.getByRole('region', { name: '3D viewer', exact: true });
  await expect(viewer).toHaveAttribute('data-state', 'ready', { timeout: 30_000 });
  await expect(panel).toHaveClass(/viewer3d-linked-panel/);
  await expect(drawing).toBeInViewport();
  await expect(viewer).toBeInViewport();

  // Navigate using real drawing controls: the nonmodal 3D panel must leave them usable.
  await drawing.getByRole('button', { name: 'Next source', exact: true }).click();
  await drawing.getByRole('button', { name: 'Next source', exact: true }).click();
  await box3.hover();
  await expect(viewer).toHaveAttribute('data-linked-hover', itemId!);
  await box3.click();
  await expect(viewer).toHaveAttribute('data-linked-selected', itemId!);
  await expect.poll(async () => JSON.parse((await viewer.getAttribute('data-highlighted-item-ids'))!)).toContain(itemId);
  await expect(viewer.getByLabel(`Item 3: ${itemId}`, { exact: true })).toHaveText('3');

  // Select a different box first so the reverse assertion cannot pass on stale selection.
  await drawing.getByRole('button', { name: 'Previous source', exact: true }).click();
  await drawing.getByRole('button', { name: 'Previous source', exact: true }).click();
  await drawing.getByTestId('evidence-box-1').click();
  await page.mouse.move(0, 0);
  await expect(box3).not.toHaveAttribute('data-linked', 'true');
  const picked = await viewer.locator('canvas').evaluate((canvas: LinkedViewerCanvas, id) => {
    if (!canvas.__viewer3d) throw new Error('Opt-in 3D pick hook is not ready');
    return canvas.__viewer3d.pick(id!);
  }, itemId);
  expect(picked).toBe(true);
  await expect(box3).toHaveAttribute('data-linked', 'true');
  await expect(drawing.getByTestId('source-position')).toHaveText(/^3 of /);
  await expect.poll(async () => {
    const box = await box3.boundingBox();
    const viewport = await drawing.getByTestId('drawing-viewport').boundingBox();
    return !!box && !!viewport && box.x >= viewport.x - 1 && box.y >= viewport.y - 1
      && box.x + box.width <= viewport.x + viewport.width + 1
      && box.y + box.height <= viewport.y + viewport.height + 1;
  }).toBe(true);
  const state = await viewer.locator('canvas').evaluate((canvas: LinkedViewerCanvas) => canvas.__viewer3d!.state());
  expect(state.highlighted).toContain(itemId);
  expect(state.labels[itemId!]).toBe('3');
});
