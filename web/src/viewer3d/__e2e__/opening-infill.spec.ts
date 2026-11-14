import { expect, test } from '@playwright/test';
import { readFile, mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import type { Viewer } from '../viewer';

// Use the real exported assets, without a running API or any source regeneration.
// Extra documents (including the end-only random sample) are supplied by the worker.
const root = fileURLToPath(new URL('../../../../', import.meta.url));
const artifacts = process.env.ARTIFACTS_DIR ?? resolve(root, 'artifacts');
const output = resolve(root, 'results/final/3D');
const docs = process.env.F3D_SCREENSHOT_DOCS?.split(',').filter(Boolean) ?? [
  'cubicasa5k__colorful-11397', 'cubicasa5k__colorful-11400',
  'swiss_dwellings__site3468-bldg5347-floor23670',
];

test.setTimeout(60_000);
for (const docId of docs) test(`opening infill: ${docId}`, async ({ page }) => {
  const folder = resolve(artifacts, docId);
  const manifest = JSON.parse(await readFile(resolve(folder, 'scene.json'), 'utf8'));
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.routeWebSocket('**/ws*', () => {});
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/scene')) return route.fulfill({ json: manifest });
    const name = path.split('/files/')[1];
    if (name && /^[\w.-]+$/.test(name)) {
      try { return await route.fulfill({ body: await readFile(resolve(folder, name)),
        contentType: name.endsWith('.glb') ? 'model/gltf-binary' : 'application/json' }); }
      catch { return route.fulfill({ status: 404 }); }
    }
    return route.fulfill({ status: 404 });
  });
  // The legacy test page maps this one ID to an offline fixture. Substitute its
  // real current export so screenshots never accidentally validate the old GLB.
  await page.route('**/fixtures/colorful-11397/**', async (route) => {
    if (route.request().url().endsWith('scene.json')) return route.fulfill({ json: { ...manifest, glb: 'scene.glb' } });
    return route.fulfill({ body: await readFile(resolve(folder, 'scene.glb')), contentType: 'model/gltf-binary' });
  });
  await page.goto(`/?doc=${encodeURIComponent(docId)}&viewer3dTest=1#/viewer-test`);
  const viewer = page.getByRole('region', { name: '3D viewer', exact: true });
  await expect(viewer).toHaveAttribute('data-state', 'ready');
  await expect.poll(() => page.evaluate(() => !!(window as typeof window & { viewer3dTest?: Viewer }).viewer3dTest)).toBe(true);
  const data = await page.evaluate(() => {
    const viewer = (window as typeof window & { viewer3dTest: Viewer }).viewer3dTest;
    viewer.clearHighlight();
    viewer.controls.update();
    return { docId: viewer.scene!.manifest.doc_id, missing: viewer.scene!.missingItemIds };
  });
  expect(data.docId).toBe(docId);
  expect(data.missing).toEqual([]);
  await mkdir(output, { recursive: true });
  await viewer.screenshot({ path: resolve(output, `${docId}-overview.png`) });
  // Orbit to expose lintels, sills and wall ends from the opposite side too.
  await page.evaluate(() => {
    const viewer = (window as typeof window & { viewer3dTest: Viewer }).viewer3dTest;
    const offset = viewer.camera.position.clone().sub(viewer.controls.target);
    offset.x *= -1; offset.z *= -1;
    viewer.camera.position.copy(viewer.controls.target).add(offset); viewer.controls.update();
  });
  await viewer.screenshot({ path: resolve(output, `${docId}-reverse.png`) });
});
