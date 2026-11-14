import { expect, test, type Page } from '@playwright/test'
import type { Viewer } from '../src/viewer3d/viewer'

// FIX-5: staged build-up with a step slider, live against the real API and scenes.
test.setTimeout(120_000)

type Win = typeof window & { visualise3dTest: Viewer }

async function openVisualise(page: Page, docId: string) {
  await page.goto('/#/viewer-test')
  await page.getByLabel('Visualise document ID', { exact: true }).fill(docId)
  await page.getByRole('button', { name: 'Visualise it', exact: true }).click()
  const panel = page.getByRole('dialog', { name: 'Visualise it', exact: true })
  await expect(panel.getByRole('region', { name: '3D viewer', exact: true })).toHaveAttribute('data-state', 'ready', { timeout: 90_000 })
  return { panel, slider: panel.getByTestId('build-slider') }
}

const scaleOf = (page: Page, id: string) => page.evaluate((item) => (window as Win).visualise3dTest.scene!.items.get(item)!.scale.y, id)
const cameraOf = (page: Page) => page.evaluate(() => (window as Win).visualise3dTest.camera.position.toArray())

test('raster plan builds floor, walls, then doors and windows; scrub both ways, pause, step; camera stays put', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  const { panel, slider } = await openVisualise(page, 'cubicasa5k__colorful-11397')
  await expect(slider).toBeVisible()
  await expect(slider).toHaveAttribute('data-total', '3')
  const label = slider.getByTestId('build-step-label')
  // It plays by itself and reaches the finished model.
  await expect(panel).toHaveAttribute('data-rise-state', 'done', { timeout: 30_000 })
  await expect(label).toHaveText('Step 3 of 3 · Doors and windows')
  await expect(slider).toHaveAttribute('data-playing', 'false')

  const range = slider.getByRole('slider', { name: 'Build step' })
  await page.waitForTimeout(1000) // the end-of-build fly-to settles before we measure
  const camera = await cameraOf(page)
  // Dragging back to step 1: only the floor; walls/doors not built; the answer's windows (highlighted) stay visible.
  await range.fill('1')
  await expect(label).toHaveText('Step 1 of 3 · Floor')
  expect(await scaleOf(page, 'wall-001')).toBe(0)
  expect(await scaleOf(page, 'door-001')).toBe(0)
  expect(await scaleOf(page, 'window-001')).toBeGreaterThan(0)
  await range.fill('2')
  await expect(label).toHaveText('Step 2 of 3 · Walls')
  expect(await scaleOf(page, 'wall-001')).toBeGreaterThan(0)
  expect(await scaleOf(page, 'door-001')).toBe(0)
  // Forward again with the step button, then back with its twin.
  await slider.getByRole('button', { name: 'Next step' }).click()
  await expect(label).toHaveText('Step 3 of 3 · Doors and windows')
  expect(await scaleOf(page, 'door-001')).toBeGreaterThan(0)
  await expect(slider.getByRole('button', { name: 'Next step' })).toBeDisabled()
  await slider.getByRole('button', { name: 'Previous step' }).click()
  await expect(label).toHaveText('Step 2 of 3 · Walls')
  expect(await cameraOf(page)).toEqual(camera)

  // Play from the middle, then pause: the slider reports a paused, whole step.
  await slider.getByRole('button', { name: 'Play build-up' }).click()
  await expect(slider).toHaveAttribute('data-playing', 'true')
  await slider.getByRole('button', { name: 'Pause build-up' }).click()
  await expect(slider).toHaveAttribute('data-playing', 'false')
  expect(await cameraOf(page)).toEqual(camera)
})

test('reduced motion shows the finished model at once and the slider still works', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  const { panel, slider } = await openVisualise(page, 'cubicasa5k__colorful-11397')
  await expect(panel).toHaveAttribute('data-rise-state', 'done')
  await expect(slider.getByTestId('build-step-label')).toHaveText('Step 3 of 3 · Doors and windows')
  expect(await scaleOf(page, 'door-001')).toBeGreaterThan(0)
  await slider.getByRole('slider', { name: 'Build step' }).fill('1')
  await expect(slider.getByTestId('build-step-label')).toHaveText('Step 1 of 3 · Floor')
  expect(await scaleOf(page, 'wall-001')).toBe(0)
  await slider.getByRole('slider', { name: 'Build step' }).fill('3')
  expect(await scaleOf(page, 'wall-001')).toBeGreaterThan(0)
})

test('IFC building builds per storey: slab, walls, openings, then roof', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  const { slider } = await openVisualise(page, 'ifc_bench__ac20-arc')
  const total = Number(await slider.getAttribute('data-total'))
  expect(total).toBeGreaterThanOrEqual(12)
  const range = slider.getByRole('slider', { name: 'Build step' })
  const label = slider.getByTestId('build-step-label')
  const labels: string[] = []
  for (let i = 1; i <= total; i++) {
    await range.fill(String(i))
    await expect(label).toHaveText(new RegExp(`^Step ${i} of ${total} · `))
    labels.push(((await label.textContent()) ?? '').split(' · ')[1])
  }
  // Lowest storey first, slab before walls before doors and windows within a storey; roof is last.
  expect(labels[0]).toBe('Keller slab')
  expect(labels.indexOf('Keller walls')).toBeGreaterThan(labels.indexOf('Keller slab'))
  expect(labels.indexOf('Keller doors and windows')).toBeGreaterThan(labels.indexOf('Keller walls'))
  expect(labels.indexOf('Erdgeschoss slab')).toBeGreaterThan(labels.indexOf('Keller doors and windows'))
  expect(labels.indexOf('2. Obergeschoss walls')).toBeGreaterThan(labels.indexOf('1. Obergeschoss walls'))
})
