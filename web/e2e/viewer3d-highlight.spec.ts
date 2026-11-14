import { expect, test, type Page } from '@playwright/test';

test.use({
  reducedMotion: 'reduce',
  actionTimeout: 15_000,
  launchOptions: {
    executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
    args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
  },
});
test.setTimeout(60_000);

async function waitForRenderedFrame(page: Page) {
  const frame = () => page.evaluate(() => (window as typeof window & {
    viewer3dTest: { renderer: { info: { render: { frame: number } } } };
  }).viewer3dTest.renderer.info.render.frame);
  const previous = await frame();
  await expect.poll(frame, { timeout: 15_000, message: 'The current geometry and materials must reach a rendered frame' })
    .toBeGreaterThan(previous);
}

test('highlight changes rendered geometry, shows citation numbers, and clears', async ({ page }, testInfo) => {
  await page.goto('/?doc=colorful-11397#/viewer-test', { timeout: 15_000 });
  await expect(page.getByRole('combobox', { name: 'Document', exact: true })).toHaveValue('colorful-11397');
  const viewer = page.getByRole('region', { name: '3D viewer', exact: true });
  await expect(viewer).toHaveAttribute('data-state', 'ready', { timeout: 30_000 });
  const canvas = viewer.locator('canvas');
  await canvas.scrollIntoViewIfNeeded();
  await waitForRenderedFrame(page);
  const clip = await canvas.boundingBox();
  expect(clip).not.toBeNull();
  const before = await page.screenshot({ clip: clip!, animations: 'disabled', path: testInfo.outputPath('before-highlight.png') });
  await page.getByRole('button', { name: 'Highlight 3 random items', exact: true }).click();
  const stateOutput = page.getByLabel('Highlight state', { exact: true });
  const state = JSON.parse((await stateOutput.textContent())!) as {
    highlighted: string[]; dimmed: number; labels: Record<string, string>;
  };
  expect(new Set(state.highlighted).size).toBe(3);
  expect(state.dimmed).toBeGreaterThan(0);
  const labels = viewer.locator('.viewer3d-item-label');
  await expect(labels).toHaveCount(3);
  for (const [index, id] of state.highlighted.entries()) {
    expect(state.labels[id]).toBe(String(index + 1));
    // CSS2DRenderer inserts overlays in scene traversal order. Citation
    // identity must stay tied to the item ID, regardless of that DOM order.
    const label = viewer.getByLabel(`Item ${index + 1}: ${id}`, { exact: true });
    await expect(label).toHaveAttribute('data-item-id', id);
    await expect(label).toHaveText(String(index + 1));
  }
  // Reduced motion applies the final camera immediately; wait for its render.
  await waitForRenderedFrame(page);
  await canvas.scrollIntoViewIfNeeded();
  const afterClip = await canvas.boundingBox();
  expect(afterClip).not.toBeNull();
  const after = await page.screenshot({ clip: afterClip!, animations: 'disabled', path: testInfo.outputPath('after-highlight.png') });
  expect(after.equals(before)).toBe(false);
  await testInfo.attach('before highlight', { body: before, contentType: 'image/png' });
  await testInfo.attach('after highlight', { body: after, contentType: 'image/png' });
  await page.getByRole('button', { name: 'Clear highlight', exact: true }).click();
  await expect(labels).toHaveCount(0);
  await expect(stateOutput).toHaveText(JSON.stringify({ highlighted: [], dimmed: 0, labels: {} }));
});
