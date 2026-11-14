import { expect, test } from '@playwright/test';
import { createReadStream } from 'node:fs';
import { mkdir, readFile, readdir, stat, writeFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import type { Viewer } from '../src/viewer3d/viewer';
import type { SceneManifest } from '../src/viewer3d/scene';

const artifacts = fileURLToPath(new URL('../../artifacts/', import.meta.url));
const results = fileURLToPath(new URL('../../results/', import.meta.url));

async function publishableModels() {
  const models = await Promise.all((await readdir(artifacts, { withFileTypes: true }))
    .filter((entry) => entry.isDirectory()).map(async (entry) => {
      const directory = join(artifacts, entry.name);
      try {
        const [doc, scene, glb] = await Promise.all([
          readFile(join(directory, 'doc.json'), 'utf8').then(JSON.parse),
          readFile(join(directory, 'scene.json'), 'utf8').then(JSON.parse),
          stat(join(directory, 'scene.glb')),
        ]);
        // Publication is explicit in current scene manifests; honour either veto.
        if (doc.publishable === false || scene.publishable === false
          || (doc.publishable !== true && scene.publishable !== true)) return null;
        return { directory, docId: scene.doc_id as string, scene: scene as SceneManifest, bytes: glb.size };
      } catch { return null; } // An artifact still being built is not a benchmark candidate.
    }));
  const sorted = models.filter((model) => model !== null).sort((a, b) => b.bytes - a.bytes);
  if (!sorted.length) throw new Error('T-07 requires at least one explicitly publishable artifact scene');
  return sorted;
}

type LoadAttempt = { doc_id: string; bytes: number; load_ms: number | null; elapsed_ms: number;
  status: 'ready' | 'over-budget' | 'error'; error?: string };

// The default headless shell uses SwiftShader on this Mac. Measure its real
// Metal GPU in full Chromium; keep this override local to the performance spec.
test.use({ channel: 'chromium', launchOptions: {
  args: ['--use-angle=metal', '--ignore-gpu-blocklist', '--enable-gpu'],
} });
test.setTimeout(180_000);
test('largest safe publishable model orbits for five seconds with p95 below 33 ms', async ({ page }, testInfo) => {
  const models = await publishableModels();
  const attempts: LoadAttempt[] = [];
  const report: Record<string, unknown> = { doc_id: null, triangles: null, draw_calls: null,
    load_ms: null, p50_ms: null, p95_ms: null, renderer: null, frames: 0,
    largest_model: { doc_id: models[0].docId, bytes: models[0].bytes, load_ms: null }, load_attempts: attempts };
  const saveReport = async () => {
    await mkdir(results, { recursive: true });
    await writeFile(join(results, 'viewer3d_perf.json'), `${JSON.stringify(report, null, 2)}\n`);
  };
  const readPerf = () => page.evaluate(() => {
    const viewer = (window as typeof window & { __viewer3d: Viewer }).__viewer3d;
    const gl = viewer.renderer.getContext();
    const debug = gl.getExtension('WEBGL_debug_renderer_info');
    return { ...viewer.perf(), renderer: debug
      ? String(gl.getParameter(debug.UNMASKED_RENDERER_WEBGL)) : String(gl.getParameter(gl.RENDERER)) };
  });

  // Stream GLBs over HTTP. route.fulfill({path}) base64-encodes the entire ~100 MB
  // file over the browser control protocol, distorting load time and using much
  // more memory than the production files endpoint. Only small JSON is fulfilled.
  const byId = new Map(models.map((model) => [model.docId, model]));
  const server = createServer((request, response) => {
    const id = decodeURIComponent((request.url ?? '').slice(1));
    const model = byId.get(id);
    if (!model) { response.writeHead(404).end(); return; }
    response.writeHead(200, { 'Content-Type': 'model/gltf-binary', 'Content-Length': model.bytes,
      'Access-Control-Allow-Origin': '*', 'Cache-Control': 'no-store' });
    const stream = createReadStream(join(model.directory, 'scene.glb'));
    stream.on('error', () => response.destroy());
    response.on('close', () => stream.destroy());
    stream.pipe(response);
  });
  await new Promise<void>((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const address = server.address();
  if (!address || typeof address === 'string') throw new Error('No artifact HTTP port');
  const fileBase = `http://127.0.0.1:${address.port}`;
  const start = Date.now();
  let selected: typeof models[number] | undefined;
  try {
    await page.route('**/api/docs/*/scene', (route) => {
      const id = decodeURIComponent(new URL(route.request().url()).pathname.split('/')[3]);
      const model = byId.get(id);
      return model ? route.fulfill({ json: model.scene }) : route.fallback();
    });
    await page.route('**/api/docs/*/files/scene.glb', (route) => {
      const id = decodeURIComponent(new URL(route.request().url()).pathname.split('/')[3]);
      return byId.has(id) ? route.fulfill({ status: 302,
        headers: { Location: `${fileBase}/${encodeURIComponent(id)}` } }) : route.fallback();
    });
    await page.route('**/api/docs/*/files/elements.json', (route) => route.fulfill({ json: [] }));
    for (const model of models) {
      // Preserve time for measurement/reporting inside the 180 s test budget.
      // Every attempted candidate gets the viewer's full 60 s load budget.
      if (Date.now() - start > 80_000) break;
      const loadStart = Date.now();
      await page.goto(`/?doc=${encodeURIComponent(model.docId)}#/viewer-test`);
      const region = page.getByRole('region', { name: '3D viewer', exact: true });
      // Worker cancellation changes loading to an actionable error at 60 s;
      // allow a separate 150 s expectation budget for slow browser scheduling.
      await expect(region).not.toHaveAttribute('data-state', 'loading', { timeout: 150_000 });
      if (await region.getAttribute('data-state') !== 'ready') {
        const attempt: LoadAttempt = { doc_id: model.docId, bytes: model.bytes, load_ms: null,
          elapsed_ms: Date.now() - loadStart, status: 'error', error: await region.getByRole('alert').innerText() };
        attempts.push(attempt);
        if (model === models[0]) report.largest_model = attempt;
        await saveReport();
        continue;
      }
      await expect.poll(() => page.evaluate(() =>
        (window as typeof window & { __viewer3d?: Viewer }).__viewer3d?.perf().frames ?? 0),
      { timeout: 15_000 }).toBeGreaterThan(0);
      const initialPerf = await readPerf();
      const loadMs = initialPerf.load_ms;
      attempts.push({ doc_id: model.docId, bytes: model.bytes, load_ms: loadMs,
        elapsed_ms: Date.now() - loadStart, status: loadMs < 60_000 ? 'ready' : 'over-budget' });
      if (model === models[0]) report.largest_model = { doc_id: model.docId, bytes: model.bytes, load_ms: loadMs };
      // Save real selected-model metrics before warm-up assertions. A slow GPU
      // must leave useful diagnostics instead of an all-null result file.
      if (loadMs < 60_000) {
        selected = model;
        Object.assign(report, { doc_id: model.docId, bytes: model.bytes, ...initialPerf, measurement: 'warmup' });
      }
      await saveReport();
      if (selected) break;
    }
    expect(selected, 'No publishable model loaded within 60 s; see load_attempts in the report').toBeDefined();
    // Measure the entire model, including its roof, after shader/upload warm-up.
    await page.evaluate(() => {
      const viewer = (window as typeof window & { __viewer3d: Viewer }).__viewer3d;
      viewer.setStorey(null);
      viewer.setShowRoof(true);
      viewer.resetPerf();
    });
    await expect.poll(async () => {
      const sample = await readPerf();
      Object.assign(report, sample);
      return sample.frames;
    },
    { timeout: 15_000 }).toBeGreaterThanOrEqual(30);

    const perf = await page.evaluate(async () => {
      const viewer = (window as typeof window & { __viewer3d: Viewer }).__viewer3d;
      const offset = viewer.camera.position.clone().sub(viewer.controls.target);
      const damping = viewer.controls.enableDamping;
      viewer.controls.enableDamping = false;
      viewer.resetPerf();
      const start = performance.now();
      await new Promise<void>((resolve) => {
        const orbit = (now: number) => {
          const angle = Math.min(1, (now - start) / 5000) * Math.PI * 2;
          const x = offset.x * Math.cos(angle) + offset.z * Math.sin(angle);
          const z = offset.z * Math.cos(angle) - offset.x * Math.sin(angle);
          viewer.camera.position.copy(viewer.controls.target).add(offset.clone().set(x, offset.y, z));
          viewer.controls.update();
          if (now - start < 5000) requestAnimationFrame(orbit);
          else resolve();
        };
        requestAnimationFrame(orbit);
      });
      viewer.controls.enableDamping = damping;
      return viewer.perf();
    });
    Object.assign(report, { doc_id: selected!.docId, bytes: selected!.bytes, triangles: perf.triangles,
      draw_calls: perf.draw_calls, load_ms: perf.load_ms, p50_ms: perf.p50_ms, p95_ms: perf.p95_ms,
      frames: perf.frames, measurement: 'five-second-orbit' });
    await saveReport();
    await testInfo.attach('viewer3d performance', { body: JSON.stringify({ ...report, frames: perf.frames }), contentType: 'application/json' });
    expect(perf.frames, 'The measured orbit must contain real rendered frames').toBeGreaterThan(100);
    expect(perf.triangles).toBeGreaterThan(0);
    expect(perf.draw_calls).toBeGreaterThan(0);
    expect(perf.load_ms).toBeGreaterThan(0);
    expect(perf.load_ms).toBeLessThan(60_000);
    expect(perf.p95_ms).toBeGreaterThan(0);
    expect(perf.p95_ms).toBeLessThan(33);
  } finally {
    await saveReport();
    server.closeAllConnections();
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
});
