import { expect, test } from '@playwright/test';
import type { HighlightState } from '../src/viewer3d/highlight';

test.use({
  launchOptions: {
    executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
    args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
  },
});

test('Visualise it raises the plan and retains the five answer citation labels', async ({ page }, testInfo) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  // Freeze the animation clock so even a slow software-rendered screenshot is flat.
  const time = new Date('2026-11-14T12:00:00Z');
  await page.clock.install({ time });
  await page.clock.pauseAt(new Date(time.getTime() + 1000));
  await page.goto('/#/viewer-test');
  await page.getByLabel('Visualise document ID', { exact: true }).fill('cubicasa5k__colorful-11397');
  await page.getByRole('button', { name: 'Visualise it', exact: true }).click();
  const panel = page.getByRole('dialog', { name: 'Visualise it', exact: true });
  await expect(panel.getByRole('region', { name: '3D viewer', exact: true })).toHaveAttribute('data-state', 'ready');
  await page.clock.runFor(32);
  await expect(panel).toHaveAttribute('data-rise-state', 'flat');
  const canvas = panel.locator('canvas');
  const flat = await canvas.screenshot({ path: testInfo.outputPath('visualise-flat.png') });
  // Skip intermediate frames: rendering every frame with SwiftShader can exhaust
  // the test timeout. Timer transitions still run when frames are skipped.
  await page.clock.fastForward(1000);
  await expect(panel).toHaveAttribute('data-rise-state', 'rising');
  await page.clock.fastForward(1000);
  await expect(panel).toHaveAttribute('data-rise-state', 'done');
  await page.clock.runFor(32);
  const state = await page.evaluate(() => (window as typeof window & {
    visualise3dTest: { getHighlightState(): HighlightState };
  }).visualise3dTest.getHighlightState());
  const ids = Array.from({ length: 5 }, (_, i) => `window-${String(i + 1).padStart(3, '0')}`);
  expect(state.highlighted).toEqual(ids);
  expect(state.labels).toEqual(Object.fromEntries(ids.map((id, i) => [id, String(i + 1)])));
  await expect(panel.locator('.viewer3d-item-label')).toHaveCount(5);
  for (const [i, id] of ids.entries()) {
    await expect(panel.getByLabel(`Item ${i + 1}: ${id}`, { exact: true })).toHaveText(String(i + 1));
  }
  const raised = await canvas.screenshot({ path: testInfo.outputPath('visualise-done.png') });
  expect(raised.equals(flat)).toBe(false);
  await testInfo.attach('flat plan', { body: flat, contentType: 'image/png' });
  await testInfo.attach('raised model', { body: raised, contentType: 'image/png' });
  await page.getByRole('button', { name: 'Close 3D view', exact: true }).click();
  await expect(panel).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Visualise it', exact: true })).toBeFocused();
});

test('missing scene shows an explanation and the panel can close', async ({ page }) => {
  await page.route('**/api/docs/missing-scene/scene', (route) => route.fulfill({
    status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'not_built' }),
  }));
  await page.goto('/#/viewer-test');
  await page.getByLabel('Visualise document ID', { exact: true }).fill('missing-scene');
  await page.getByRole('button', { name: 'Visualise it', exact: true }).click();
  const panel = page.getByRole('dialog', { name: 'Visualise it', exact: true });
  await expect(panel).toHaveAttribute('data-rise-state', 'error');
  await expect(panel.getByRole('alert')).toHaveText('3D model not available for this document');
  await page.keyboard.press('Escape');
  await expect(panel).toHaveCount(0);
});

test('reduced motion opens directly in the completed 3D view', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/#/viewer-test');
  await page.getByRole('button', { name: 'Visualise it', exact: true }).click();
  const panel = page.getByRole('dialog', { name: 'Visualise it', exact: true });
  await expect(panel).toHaveAttribute('data-rise-state', 'done');
  await expect(panel.locator('.viewer3d-item-label')).toHaveCount(5);
});
