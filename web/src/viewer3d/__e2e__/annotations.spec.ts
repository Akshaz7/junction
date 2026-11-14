import { expect, test, type Page } from '@playwright/test';
import type { Viewer } from '../viewer';

test.setTimeout(60_000);

async function ready(page: Page) {
  await page.goto('/?doc=colorful-11397&viewer3dTest=1#/viewer-test');
  await expect(page.getByRole('region', { name: '3D viewer', exact: true })).toHaveAttribute('data-state', 'ready');
  await expect.poll(() => page.evaluate(() => Boolean((window as typeof window & { viewer3dTest?: Viewer }).viewer3dTest)))
    .toBe(true);
}

async function assertPacked(page: Page) {
  const boxes = await page.locator('.viewer3d-label-pill').evaluateAll((nodes) => nodes
    .filter((node) => getComputedStyle(node).visibility === 'visible' && node.getBoundingClientRect().width > 0)
    .map((node) => { const b = node.getBoundingClientRect(); return { x: b.x, y: b.y, right: b.right, bottom: b.bottom }; }));
  expect(boxes.length).toBeGreaterThan(0);
  for (const [i, a] of boxes.entries()) for (const b of boxes.slice(i + 1)) {
    expect(a.right <= b.x || b.right <= a.x || a.bottom <= b.y || b.bottom <= a.y).toBe(true);
  }
}

test('evidence glows in its fixed kind colour, preserves building materials, flies smoothly to the first item, and packs floating labels', async ({ page }) => {
  await ready(page);
  const result = await page.evaluate(() => {
    const viewer = (window as typeof window & { viewer3dTest: Viewer }).viewer3dTest;
    const scene = viewer.scene!;
    const ids = [...scene.items.keys()].filter((id) => scene.manifest.items[id].kind === 'window');
    const others: { mesh: { material: unknown }; material: unknown }[] = [];
    scene.root.traverse((node) => {
      const mesh = node as typeof node & { isMesh?: boolean; material: unknown };
      let owner: string | undefined;
      for (let current: typeof node | null = node; current; current = current.parent) {
        owner = scene.itemIdsByObject.get(current);
        if (owner) break;
      }
      if (mesh.isMesh && (!owner || !ids.includes(owner))) others.push({ mesh, material: mesh.material });
    });
    const before = viewer.camera.position.toArray();
    viewer.highlight(ids, { labels: Object.fromEntries(ids.map((id, i) => [id, String(i + 1)])) });
    const immediate = viewer.camera.position.toArray();
    const first = scene.items.get(ids[0])!;
    const centre = viewer.controls.target.clone().set(0, 0, 0);
    let amber = true;
    first.traverse((node) => {
      const mesh = node as typeof node & { isMesh?: boolean; material: { emissive?: { getHexString(): string } } };
      if (mesh.isMesh && mesh.material.emissive) amber &&= mesh.material.emissive.getHexString() === '0072b2'  // fixed window colour (Okabe-Ito blue), see lib/kind-colors.ts;
    });
    // Plan-map fixture nodes have local geometry; bbox centre is authoritative here.
    const bounds = scene.manifest.items[ids[0]].bbox_m!;
    centre.set(...bounds[0]).add(viewer.controls.target.clone().set(...bounds[1])).multiplyScalar(0.5);
    return { before, immediate, amber, preserved: others.every(({ mesh, material }) => mesh.material === material),
      centre: centre.toArray(), ids };
  });
  expect(result.amber).toBe(true);
  expect(result.preserved).toBe(true);
  expect(result.immediate).toEqual(result.before);
  await expect.poll(() => page.evaluate((target) => {
    const viewer = (window as typeof window & { viewer3dTest: Viewer }).viewer3dTest;
    return viewer.controls.target.distanceTo(viewer.controls.target.clone().set(...target as [number, number, number]));
  }, result.centre)).toBeLessThan(0.01);
  await expect(page.locator('.viewer3d-annotation')).toHaveCount(result.ids.length);
  await expect(page.locator('.viewer3d-label-kind').first()).toHaveText('window');
  await expect(page.locator('.viewer3d-label-leader').first()).toHaveAttribute('style', /width: [\d.]+px/);
  expect(await page.locator('.viewer3d-label-pill').first().evaluate((node) => getComputedStyle(node).backgroundColor))
    .toBe('rgb(37, 39, 35)');
  await assertPacked(page);
  await page.evaluate(() => {
    const viewer = (window as typeof window & { viewer3dTest: Viewer }).viewer3dTest;
    const delta = viewer.camera.position.clone().sub(viewer.controls.target);
    const x = delta.x; delta.x = delta.z; delta.z = -x;
    viewer.camera.position.copy(viewer.controls.target).add(delta);
    viewer.controls.update();
  });
  await page.setViewportSize({ width: 700, height: 1000 });
  await expect.poll(() => page.locator('.viewer3d-label-pill').evaluateAll((nodes) => nodes.filter((n) => getComputedStyle(n).visibility === 'visible').length))
    .toBeGreaterThan(0);
  await assertPacked(page);
});

test('clicking an item opens a positioned callout with API name, type, storey and measured size', async ({ page, request }) => {
  const fixture = await (await request.get('/fixtures/colorful-11397/scene.json')).json();
  const windows = Object.keys(fixture.items).filter((key) => fixture.items[key].kind === 'window');
  await page.route('**/api/docs/t21-generated-for-demo/scene', (route) => route.fulfill({ json: {
    ...fixture, doc_id: 't21-generated-for-demo', glb: '/fixtures/colorful-11397/scene.glb',
  } }));
  // API geometry resolution follows the contract's files route.
  await page.route('**/api/docs/t21-generated-for-demo/files/scene.glb', async (route) => {
    const model = await request.get('/fixtures/colorful-11397/scene.glb');
    await route.fulfill({ body: await model.body(), contentType: 'model/gltf-binary' });
  });
  await page.route('**/api/docs/t21-generated-for-demo/files/elements.json', (route) => route.fulfill({ status: 404 }));
  await page.route('**/api/docs/t21-generated-for-demo/items/*', (route) => route.fulfill({ json: {
    item_id: decodeURIComponent(route.request().url().split('/').pop()!.split('?')[0]), name: 'Demo window — generated for demo', kind: 'window', type_name: 'Fixed glazing',
    storey: 'Ground', quantities: { width_m: 1.2, height_m: 1.4 },
  } }));
  await page.goto('/?doc=t21-generated-for-demo&viewer3dTest=1#/viewer-test');
  const viewer = page.getByRole('region', { name: '3D viewer', exact: true });
  await expect(viewer).toHaveAttribute('data-state', 'ready');
  await expect.poll(() => page.evaluate(() => Boolean((window as typeof window & { viewer3dTest?: Viewer }).viewer3dTest))).toBe(true);
  // A window can sit behind the wall that holds it from the flown-to angle: use the first
  // one whose projected centre actually hits its own geometry.
  let id = windows[0];
  for (const candidate of windows) {
    await page.evaluate((id) => (window as typeof window & { viewer3dTest: Viewer }).viewer3dTest.highlight([id]), candidate);
    await expect.poll(() => page.evaluate((id) => {
      const v = (window as typeof window & { viewer3dTest: Viewer }).viewer3dTest;
      const bounds = v.scene!.manifest.items[id].bbox_m!;
      const p = v.controls.target.clone().set(...bounds[0])
        .add(v.controls.target.clone().set(...bounds[1])).multiplyScalar(0.5);
      return v.controls.target.distanceTo(p);
    }, candidate)).toBeLessThan(0.001);
    // Hit actual geometry at its projected centre after the camera flight settles.
    const hit = await page.evaluate((id) => {
      const v = (window as typeof window & { viewer3dTest: Viewer }).viewer3dTest;
      const p = v.itemScreenPosition(id)!;
      const rect = v.renderer.domElement.getBoundingClientRect();
      return v.pick(rect.x + p.x, rect.y + p.y);
    }, candidate);
    if (hit === candidate) { id = candidate; break; }
  }
  const point = await page.evaluate((id) => {
    const v = (window as typeof window & { viewer3dTest: Viewer }).viewer3dTest;
    const p = v.itemScreenPosition(id)!;
    const r = v.renderer.domElement.getBoundingClientRect();
    return { x: r.x + p.x, y: r.y + p.y };
  }, id);
  await page.mouse.click(point.x, point.y);
  const card = viewer.getByRole('complementary', { name: 'Item details' });
  await expect(card.getByRole('heading')).toHaveText('Demo window — generated for demo');
  for (const text of ['Fixed glazing', 'Ground', '1.2 m', '1.4 m']) await expect(card.getByText(text, { exact: true })).toBeVisible();
  await expect(card).toHaveAttribute('data-anchored', 'true');
  await page.keyboard.press('Escape');
  await expect(card).toHaveCount(0);
});
