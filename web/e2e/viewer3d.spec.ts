import { expect, test, type Locator } from '@playwright/test';

test.use({
  launchOptions: {
    executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
    args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
  },
});

async function readModelPixels(canvas: Locator) {
  return canvas.evaluate((element: HTMLCanvasElement) => new Promise<{
    fraction: number; pickX: number; pickY: number;
  }>((resolve, reject) => {
    // Read in the viewer's next render frame, before the browser discards the
    // default framebuffer. Production does not need preserveDrawingBuffer.
    requestAnimationFrame(() => {
      try {
        const gl = element.getContext('webgl2');
        if (!gl) throw new Error('The viewer has no WebGL2 context');
        const width = gl.drawingBufferWidth;
        const height = gl.drawingBufferHeight;
        const pixels = new Uint8Array(width * height * 4);
        gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
        if (gl.getError() !== gl.NO_ERROR) throw new Error('Could not read the canvas pixels');
        if (pixels[3] !== 255) throw new Error('The viewer has not rendered an opaque frame');

        // The fitted model leaves the bottom-left corner as background. Using
        // that color also rejects a canvas uniformly filled with a wrong color.
        const isModel = (offset: number) => pixels[offset + 3] > 0 && (
          Math.abs(pixels[offset] - pixels[0]) > 18
          || Math.abs(pixels[offset + 1] - pixels[1]) > 18
          || Math.abs(pixels[offset + 2] - pixels[2]) > 18
        );
        let count = 0;
        let nearest = Infinity;
        let pickX = 0;
        let pickY = 0;
        for (let y = 0; y < height; y++) {
          for (let x = 0; x < width; x++) {
            const offset = (y * width + x) * 4;
            if (!isModel(offset)) continue;
            count++;
            // Choose an interior model pixel for the raycast, away from edges.
            if (x < 2 || x >= width - 2 || y < 2 || y >= height - 2
              || !isModel(offset - 8) || !isModel(offset + 8)
              || !isModel(offset - width * 8) || !isModel(offset + width * 8)) continue;
            const distance = (x - width / 2) ** 2 + (y - height / 2) ** 2;
            if (distance < nearest) {
              nearest = distance;
              pickX = x;
              pickY = y;
            }
          }
        }
        const rect = element.getBoundingClientRect();
        resolve({
          fraction: count / (width * height),
          pickX: rect.left + (pickX + 0.5) / width * rect.width,
          pickY: rect.top + (height - pickY - 0.5) / height * rect.height,
        });
      } catch (error) { reject(error); }
    });
  }));
}

test('DigitalHub renders with software GL, filters storeys, and picks an item', async ({ page, request }) => {
  await page.goto('/#/viewer-test');
  const viewer = page.getByRole('region', { name: '3D viewer', exact: true });
  const canvas = viewer.locator('canvas');
  await expect(viewer).toHaveAttribute('data-state', 'ready');
  await expect(canvas).toBeVisible();
  await expect.poll(async () => (await readModelPixels(canvas)).fraction).toBeGreaterThan(0.01);

  const filter = viewer.getByRole('combobox', { name: 'Storey', exact: true });
  await filter.selectOption({ label: 'E00_OKRD' });
  await expect(filter).toHaveValue('E00_OKRD');
  await expect.poll(async () => (await readModelPixels(canvas)).fraction).toBeGreaterThan(0.01);
  const pixels = await readModelPixels(canvas);
  await page.mouse.click(pixels.pickX, pixels.pickY);
  const picked = viewer.getByLabel('Picked item', { exact: true });
  await expect(picked).not.toHaveText('No item selected');
  const response = await request.get('/fixtures/digital_hub/scene.json');
  expect(response.ok()).toBe(true);
  const manifest = await response.json();
  expect(manifest.items[(await picked.textContent())!]?.storey).toBe('E00_OKRD');
  await filter.selectOption({ label: 'All storeys' });
  await expect(picked).toHaveText('No item selected');
});
