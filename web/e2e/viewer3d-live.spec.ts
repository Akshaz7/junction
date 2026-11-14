import { expect, test, type Page } from '@playwright/test';
import type { HighlightState } from '../src/viewer3d/highlight';

test.use({
  actionTimeout: 15_000,
  launchOptions: {
    executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
    args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
  },
});
test.setTimeout(60_000);

const readState = (page: Page) => page.evaluate(() => (window as typeof window & {
  viewer3dTest: { getHighlightState(): HighlightState };
}).viewer3dTest.getHighlightState());

async function ready(page: Page, name: string) {
  const started = Date.now();
  const log = (message: string) => console.log(`[${name} +${Date.now() - started}ms] ${message}`);
  page.on('pageerror', (error) => log(`page error: ${error.message}`));
  page.on('websocket', (socket) => {
    if (new URL(socket.url()).pathname !== '/ws') return;
    log('WebSocket created');
    socket.on('close', () => log('WebSocket closed'));
    socket.on('socketerror', (error) => log(`WebSocket error: ${error}`));
  });
  // StrictMode closes its first connection and creates another. Observe the
  // application's actual sockets without importing another Vite module instance
  // or waiting for a probe on a connection that may already have been closed.
  await page.addInitScript(() => {
    const sockets: WebSocket[] = [];
    Object.assign(window, { viewer3dLiveSockets: sockets });
    window.WebSocket = class extends WebSocket {
      constructor(url: string | URL, protocols?: string | string[]) {
        super(url, protocols);
        if (new URL(this.url).pathname === '/ws') sockets.push(this);
      }
    };
  });
  log('navigating');
  await page.goto('/?doc=colorful-11397#/viewer-test', { timeout: 15_000 });
  await expect(page.getByRole('combobox', { name: 'Document', exact: true })).toHaveValue('colorful-11397');
  await expect(page.getByRole('region', { name: '3D viewer', exact: true }),
    `${name}: light fixture geometry must finish loading`).toHaveAttribute('data-state', 'ready', { timeout: 30_000 });
  log('fixture ready');
  await expect.poll(() => page.evaluate(() => Boolean((window as typeof window & {
    viewer3dTest?: unknown;
  }).viewer3dTest)), { timeout: 9000, message: `${name}: viewer test API must be available` }).toBe(true);
  await expect.poll(() => page.evaluate(() => (window as typeof window & {
    viewer3dLiveSockets: WebSocket[];
  }).viewer3dLiveSockets.at(-1)?.readyState === WebSocket.OPEN), {
    timeout: 9000, message: `${name}: an active application /ws handshake must complete`,
  }).toBe(true);
  log('viewer API and live connection ready');
}

test('two browser contexts share three highlighted items, their labels, and clear within 2 seconds', async ({ browser, baseURL }) => {
  const a = await browser.newContext({ baseURL, reducedMotion: 'reduce' });
  const b = await browser.newContext({ baseURL, reducedMotion: 'reduce' });
  try {
    const pageA = await a.newPage();
    const pageB = await b.newPage();
    await ready(pageA, 'A');
    await ready(pageB, 'B');
    console.log('[live] A selects three items');
    await pageA.getByRole('button', { name: 'Highlight 3 random items', exact: true }).click();
    const expected = await readState(pageA);
    expect(expected.highlighted).toHaveLength(3);
    expect(Object.values(expected.labels)).toEqual(['1', '2', '3']);
    await expect.poll(() => readState(pageB), {
      timeout: 2000, intervals: [50, 100], message: 'B must receive A’s three IDs and labels within 2 seconds',
    }).toEqual(expected);
    await expect(pageB.locator('.viewer3d-item-label')).toHaveCount(3, { timeout: 15_000 });
    console.log('[live] B received three items; A changes citation labels');
    // Evidence labels need not be 1..N; the server must preserve this map.
    const labels = Object.fromEntries(expected.highlighted.map((id, i) => [id, ['7', '12', '19'][i]]));
    await pageA.evaluate(({ ids, labels }) => (window as typeof window & {
      viewer3dTest: { highlight(ids: string[], options: { labels: Record<string, string> }): void };
    }).viewer3dTest.highlight(ids, { labels }), { ids: expected.highlighted, labels });
    await expect.poll(() => readState(pageB), {
      timeout: 2000, intervals: [50, 100], message: 'B must receive custom citation labels within 2 seconds',
    }).toEqual({ ...expected, labels });
    console.log('[live] B received custom labels; B clears the highlight');
    await pageB.getByRole('button', { name: 'Clear highlight', exact: true }).click();
    await expect.poll(() => readState(pageA), {
      timeout: 2000, intervals: [50, 100], message: 'A must receive B’s clear within 2 seconds',
    }).toEqual({
      highlighted: [], dimmed: 0, labels: {},
    });
    console.log('[live] bidirectional highlight sync passed');
  } finally {
    await Promise.allSettled([a.close(), b.close()]);
  }
});
