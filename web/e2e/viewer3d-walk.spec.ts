import { expect, test, type Page } from '@playwright/test';
import type { Viewer } from '../src/viewer3d/viewer';
import { cutawayStoreys } from '../src/viewer3d/cutaway';

test.use({
  reducedMotion: 'reduce',
  launchOptions: {
    executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
    args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
  },
});
test.setTimeout(60_000);
const docId = 'ifc_bench__ac20-arc';
type TestWindow = typeof window & { __viewer3d: Viewer };
const state = (page: Page) => page.evaluate(() => (window as TestWindow).__viewer3d.walk());
const camera = (page: Page) => page.evaluate(() => {
  const viewer = (window as TestWindow).__viewer3d;
  return { position: viewer.camera.position.toArray(), quaternion: viewer.camera.quaternion.toArray(),
    target: viewer.controls.target.toArray(), near: viewer.camera.near };
});
function expectCamera(actual: Awaited<ReturnType<typeof camera>>, expected: Awaited<ReturnType<typeof camera>>) {
  for (const field of ['position', 'quaternion', 'target'] as const) {
    actual[field].forEach((value, index) => expect(value).toBeCloseTo(expected[field][index], 8));
  }
  expect(actual.near).toBe(expected.near);
}

test('AC20 walks at eye height inside the ground room, collides, changes storeys, preserves edits and restores orbit', async ({ page }) => {
  await page.goto(`/?doc=${docId}&viewer3dTest=1#/viewer-test`);
  const viewer = page.getByRole('region', { name: '3D viewer', exact: true });
  await expect(viewer).toHaveAttribute('data-state', 'ready', { timeout: 30_000 });
  const manifest = await page.evaluate(() => (window as TestWindow).__viewer3d.scene!.manifest);
  const storeys = cutawayStoreys(manifest);
  const ground = storeys.find((entry) => entry.elevation_m !== undefined && entry.elevation_m >= 0)!;
  const rooms = Object.entries(manifest.items).filter(([, item]) => item.kind === 'room'
    && (typeof item.storey === 'string' ? item.storey : item.storey?.name) === ground.name && item.bbox_m);
  const area = (box: NonNullable<(typeof manifest.items)[string]['bbox_m']>) => (box[1][0] - box[0][0]) * (box[1][2] - box[0][2]);
  rooms.sort((a, b) => area(b[1].bbox_m!) - area(a[1].bbox_m!));
  const largest = rooms[0][1].bbox_m!;
  const previous = await camera(page);
  const toggle = viewer.getByRole('button', { name: 'Walk', exact: true });
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-pressed', 'true');
  const initial = await state(page);
  expect(initial.active).toBe(true);
  expect(initial.storey).toBe(ground.name);
  expect(initial.eye_height_m).toBe(1.6);
  expect(Math.abs(initial.position[1] - ground.elevation_m! - 1.6)).toBeLessThan(0.05);
  expect(initial.position[0]).toBeCloseTo((largest[0][0] + largest[1][0]) / 2, 3);
  expect(initial.position[2]).toBeCloseTo((largest[0][2] + largest[1][2]) / 2, 3);
  await page.keyboard.down('w');
  await page.waitForTimeout(1000);
  await page.keyboard.up('w');
  const moved = await state(page);
  expect(Math.hypot(moved.position[0] - initial.position[0], moved.position[2] - initial.position[2])).toBeGreaterThan(0.1);
  expect(moved.position[1]).toBe(initial.position[1]);
  expect(moved.position[0]).toBeGreaterThan(largest[0][0]);
  expect(moved.position[0]).toBeLessThan(largest[1][0]);
  expect(moved.position[2]).toBeGreaterThan(largest[0][2]);
  expect(moved.position[2]).toBeLessThan(largest[1][2]);
  const wallsContainingEye = Object.entries(manifest.items).filter(([, item]) => {
    if (item.kind !== 'wall' || !item.bbox_m) return false;
    return moved.position.every((value, i) => value > item.bbox_m![0][i] + 0.001 && value < item.bbox_m![1][i] - 0.001);
  });
  expect(wallsContainingEye).toEqual([]);

  // Looking changes orientation without moving away from the storey's eye plane.
  const canvas = viewer.getByLabel('3D building model', { exact: true });
  const box = (await canvas.boundingBox())!;
  const beforeLook = await camera(page);
  await page.mouse.move(box.x + box.width * 0.6, box.y + box.height * 0.5);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.8, box.y + box.height * 0.6, { steps: 4 });
  await page.mouse.up();
  expect((await camera(page)).quaternion).not.toEqual(beforeLook.quaternion);
  expect((await state(page)).position).toEqual(moved.position);

  await page.keyboard.press('PageUp');
  const upper = storeys[storeys.indexOf(ground) + 1];
  await expect.poll(() => state(page)).toMatchObject({ active: true, storey: upper.name });
  expect((await state(page)).position[1]).toBeCloseTo(upper.elevation_m! + 1.6, 3);
  await expect(viewer).toHaveAttribute('data-active-storey', upper.name);
  await expect(viewer.getByRole('checkbox', { name: 'Show roof', exact: true })).not.toBeChecked();
  await page.keyboard.press('q');
  expect((await state(page)).storey).toBe(ground.name);
  await page.keyboard.press('Escape');
  await expect(toggle).toHaveAttribute('aria-pressed', 'false');
  expect((await state(page)).active).toBe(false);
  expectCamera(await camera(page), previous);

  // An explicit answer target takes precedence over the largest-room fallback.
  const target = rooms[1];
  const windowId = Object.keys(manifest.items).find((id) => manifest.items[id].kind === 'window')!;
  await page.evaluate(({ target, windowId }) => {
    const viewer = (window as TestWindow).__viewer3d;
    viewer.applyCommand({ op: 'hide', item_ids: [windowId] });
    viewer.highlight([target], { cameraTargetItemId: target, labels: { [target]: '7' } });
  }, { target: target[0], windowId });
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-pressed', 'true');
  const targeted = await state(page);
  expect(targeted.position[0]).toBeCloseTo((target[1].bbox_m![0][0] + target[1].bbox_m![1][0]) / 2, 3);
  expect(targeted.position[2]).toBeCloseTo((target[1].bbox_m![0][2] + target[1].bbox_m![1][2]) / 2, 3);
  const retained = await page.evaluate(() => {
    const viewer = (window as TestWindow).__viewer3d;
    return { commands: viewer.getCommandState(), highlights: viewer.getHighlightState(),
      canvasWalk: (document.querySelector('canvas') as HTMLCanvasElement & { __viewer3d: { walk(): unknown } }).__viewer3d.walk() };
  });
  expect(retained.commands.hidden).toContain(windowId);
  expect(retained.highlights.labels[target[0]]).toBe('7');
  expect(retained.canvasWalk).toMatchObject({ active: true, eye_height_m: 1.6 });
  // Repeated toggles must not accumulate handlers or change the orbit snapshot.
  await toggle.click();
  const targetedOrbit = await camera(page);
  await toggle.click(); await page.keyboard.press('Escape');
  expectCamera(await camera(page), targetedOrbit);
  await page.evaluate(() => (window as TestWindow).__viewer3d.applyCommand({ op: 'reset', item_ids: [] }));
});

test.describe('phone walk controls', () => {
  test.use({ hasTouch: true, isMobile: true, viewport: { width: 430, height: 932 } });
  test('left joystick moves while a second touch drags the canvas to look', async ({ page, context }) => {
    await page.goto(`/?doc=${docId}#/viewer-test`);
    const viewer = page.getByRole('region', { name: '3D viewer', exact: true });
    await expect(viewer).toHaveAttribute('data-state', 'ready', { timeout: 30_000 });
    const toggle = viewer.getByRole('button', { name: 'Walk', exact: true });
    const orbit = await camera(page);
    await toggle.tap();
    const stick = viewer.getByRole('group', { name: 'Walk movement joystick', exact: true });
    await expect(stick).toBeVisible();
    const initial = await camera(page);
    const pad = (await stick.boundingBox())!;
    const canvas = (await viewer.getByLabel('3D building model', { exact: true }).boundingBox())!;
    const cdp = await context.newCDPSession(page);
    const left = { id: 0, x: pad.x + pad.width / 2, y: pad.y + pad.height / 2 - 30 };
    const right = { id: 1, x: canvas.x + canvas.width * 0.7, y: canvas.y + canvas.height * 0.5 };
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [left] });
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [left, right] });
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [left, { ...right, x: right.x + 40 }] });
    await page.waitForTimeout(600);
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    const moved = await camera(page);
    expect(moved.position).not.toEqual(initial.position);
    expect(moved.quaternion).not.toEqual(initial.quaternion);
    expect(moved.position[1]).toBe(initial.position[1]);
    await page.waitForTimeout(200);
    expect((await camera(page)).position).toEqual(moved.position);
    await toggle.tap();
    expectCamera(await camera(page), orbit);
    await expect(toggle).toHaveAttribute('aria-pressed', 'false');
    await cdp.detach();
  });
});
