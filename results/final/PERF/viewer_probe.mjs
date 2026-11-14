// Run via scripts/heavy.sh node results/final/PERF/viewer_probe.mjs.
// Times existing real GLBs in the local viewer; no generated fixture geometry.
import { chromium } from '../../../web/node_modules/playwright/index.mjs';
import { createReadStream } from 'node:fs';
import { readdir, readFile, stat, writeFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';

const root = fileURLToPath(new URL('../../../', import.meta.url));
const art = join(root, 'artifacts');
const output = fileURLToPath(new URL('./viewer.json', import.meta.url));
const models = [];
for (const entry of await readdir(art, { withFileTypes: true })) {
  if (!entry.isDirectory()) continue;
  const directory = join(art, entry.name);
  try {
    const scene = JSON.parse(await readFile(join(directory, 'scene.json'), 'utf8'));
    if (scene.publishable === false) continue;
    const bytes = (await stat(join(directory, 'scene.glb'))).size;
    models.push({ doc_id: entry.name, scene, bytes, directory });
  } catch { /* unfinished artifacts are not timing candidates */ }
}
models.sort((a, b) => b.bytes - a.bytes);
const selected = models.slice(0, 3);
const report = { viewer_changed: false, status: 'pending', models: selected.map(m => ({
  doc_id: m.doc_id, scene_glb_bytes: m.bytes, first_render_ms: null,
})), reason: null };
let browser, server;
try {
  browser = await chromium.launch({ headless: true, channel: 'chromium',
    args: ['--use-angle=metal', '--ignore-gpu-blocklist', '--enable-gpu'] });
  const byId = new Map(selected.map(m => [m.doc_id, m]));
  server = createServer((req, res) => {
    const model = byId.get(decodeURIComponent(req.url.slice(1)));
    if (!model) { res.writeHead(404).end(); return; }
    res.writeHead(200, { 'Content-Type': 'model/gltf-binary', 'Content-Length': model.bytes,
      'Access-Control-Allow-Origin': '*', 'Cache-Control': 'no-store' });
    const stream = createReadStream(join(model.directory, 'scene.glb'));
    stream.on('error', () => res.destroy());
    res.on('close', () => stream.destroy());
    stream.pipe(res);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const page = await browser.newPage();
  await page.route('**/api/docs/*/scene', route => {
    const model = byId.get(decodeURIComponent(new URL(route.request().url()).pathname.split('/')[3]));
    return model ? route.fulfill({ json: model.scene }) : route.fallback();
  });
  await page.route('**/api/docs/*/files/scene.glb', route => {
    const id = decodeURIComponent(new URL(route.request().url()).pathname.split('/')[3]);
    return route.fulfill({ status: 302, headers: { Location: `http://127.0.0.1:${server.address().port}/${encodeURIComponent(id)}` } });
  });
  await page.route('**/api/docs/*/files/elements.json', route => route.fulfill({ json: [] }));
  for (const model of report.models) {
    const started = Date.now();
    await page.goto(`http://localhost:5173/?doc=${encodeURIComponent(model.doc_id)}#/viewer-test`);
    await page.waitForFunction(() => window.__viewer3d?.perf().frames > 0, {}, { timeout: 90000 });
    Object.assign(model, await page.evaluate(() => window.__viewer3d.perf()), { elapsed_ms: Date.now() - started });
    model.first_render_ms = model.load_ms;
  }
  report.status = 'measured';
} catch (error) {
  report.status = 'blocked';
  const lines = String(error).split('\n');
  report.reason = [lines[0], ...lines.filter(line => /EPERM|SIGABRT|Permission denied|Operation not permitted|bootstrap_check_in/.test(line))].join('\n').slice(0, 1600);
} finally {
  if (browser) await browser.close();
  if (server) server.close();
  await writeFile(output, JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify(report));
}
