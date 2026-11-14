import { expect, test } from '@playwright/test';

test.use({
  launchOptions: {
    executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
    args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
  },
});

test('highlight changes rendered geometry, shows citation numbers, and clears', async ({ page }, testInfo) => {
  await page.goto('/#/viewer-test');
  const viewer = page.getByRole('region', { name: '3D viewer', exact: true });
  await expect(viewer).toHaveAttribute('data-state', 'ready');
  const canvas = viewer.locator('canvas');
  const before = await canvas.screenshot({ path: testInfo.outputPath('before-highlight.png') });
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
  // Wait for the 600ms flight before recording the final rendered frame.
  await page.waitForTimeout(750);
  const after = await canvas.screenshot({ path: testInfo.outputPath('after-highlight.png') });
  expect(after.equals(before)).toBe(false);
  await testInfo.attach('before highlight', { body: before, contentType: 'image/png' });
  await testInfo.attach('after highlight', { body: after, contentType: 'image/png' });
  await page.getByRole('button', { name: 'Clear highlight', exact: true }).click();
  await expect(labels).toHaveCount(0);
  await expect(stateOutput).toHaveText(JSON.stringify({ highlighted: [], dimmed: 0, labels: {} }));
});
