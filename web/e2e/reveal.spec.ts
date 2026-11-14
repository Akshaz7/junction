import { expect, test, type Page } from '@playwright/test'
import type { Viewer } from '../src/viewer3d/viewer'

// Answer reveal: dim the rest, one orbit, answer items light up one by one with their tags. Live API scenes.
test.setTimeout(120_000)
type Win = typeof window & { viewer3dTest: Viewer }

async function open(page: Page, reducedMotion: 'reduce' | 'no-preference') {
  await page.emulateMedia({ reducedMotion })
  await page.goto('/?doc=colorful-11397&viewer3dTest=1#/viewer-test')
  await expect(page.getByRole('region', { name: '3D viewer', exact: true }).first()).toHaveAttribute('data-state', 'ready', { timeout: 90_000 })
  await expect.poll(() => page.evaluate(() => Boolean((window as Win).viewer3dTest))).toBe(true)
  if (reducedMotion === 'no-preference') await page.waitForTimeout(2300) // a reveal needs an already-open view
}
const kindIds = (page: Page, kind: string) => page.evaluate((k) => {
  const scene = (window as Win).viewer3dTest.scene!
  return [...scene.items.keys()].filter((id) => scene.manifest.items[id].kind === k)
}, kind)
const cine = (page: Page) => page.evaluate(() => (window as Win).viewer3dTest.getCinematicState())

test('a new highlight orbits once, dims the rest, and lights items and tags one by one', async ({ page }) => {
  await open(page, 'no-preference')
  const doors = (await kindIds(page, 'door')).slice(0, 6)
  const samples = await page.evaluate(async (ids) => {
    const viewer = (window as Win).viewer3dTest
    const wall = [...viewer.scene!.items.keys()].find((id) => viewer.scene!.manifest.items[id].kind === 'wall')!
    const opacityOf = (id: string) => { let o = 1; viewer.scene!.items.get(id)!.traverse((n) => { const m = (n as { material?: { opacity: number } }).material; if (m && !Array.isArray(m)) o = Math.min(o, m.opacity) }); return o }
    const target = viewer.controls.target.clone()
    const radius = () => Math.hypot(viewer.camera.position.x - target.x, viewer.camera.position.z - target.z)
    const azimuth = () => Math.atan2(viewer.camera.position.x - target.x, viewer.camera.position.z - target.z)
    const start = { azimuth: azimuth(), radius: radius() }
    viewer.highlight(ids, { cinematic: true })
    const out: { t: number; lit: number; popped: number; dim: number; orbit: boolean; azimuth: number; radius: number; wall: number }[] = []
    const t0 = performance.now()
    while (viewer.getCinematicState().active && performance.now() - t0 < 12_000) {
      const s = viewer.getCinematicState()
      out.push({ t: performance.now() - t0, lit: s.lit, popped: s.popped, dim: s.dim, orbit: s.orbit, azimuth: azimuth(), radius: radius(), wall: opacityOf(wall) })
      await new Promise((r) => setTimeout(r, 50))
    }
    const settled = ids.map((id) => { let e = -1; viewer.scene!.items.get(id)!.traverse((n) => { const m = (n as { material?: { emissiveIntensity?: number } }).material; if (m && !Array.isArray(m) && m.emissiveIntensity !== undefined) e = m.emissiveIntensity }); return e })
    return { out, start, settled, wallEnd: opacityOf(wall), end: viewer.getCinematicState() }
  }, doors)
  const { out } = samples
  expect(out.length).toBeGreaterThan(10)
  expect(out[0].orbit).toBe(true)
  // Orbit: the azimuth sweeps a full turn.
  const sweep = Math.max(...out.map((s) => Math.abs(Math.atan2(Math.sin(s.azimuth - samples.start.azimuth), Math.cos(s.azimuth - samples.start.azimuth)))))
  expect(sweep).toBeGreaterThan(2)
  // One by one: lit and popped counts only go up, one step at a time, and reach every item.
  for (let i = 1; i < out.length; i++) { expect(out[i].lit).toBeGreaterThanOrEqual(out[i - 1].lit); expect(out[i].popped).toBeGreaterThanOrEqual(out[i - 1].popped) }
  expect(out.some((s) => s.lit > 0 && s.lit < doors.length)).toBe(true)
  expect(Math.max(...out.map((s) => s.lit))).toBe(doors.length)
  // Dim: the other geometry drops to about 55 % opacity during the reveal and returns after.
  expect(Math.min(...out.map((s) => s.wall))).toBeLessThan(0.7)
  expect(Math.min(...out.map((s) => s.wall))).toBeGreaterThan(0.4)
  expect(samples.wallEnd).toBe(1)
  expect(samples.end.active).toBe(false)
  expect(samples.settled).toEqual(doors.map(() => 2.8))
  await expect(page.locator('.viewer3d-annotation[data-pop]')).toHaveCount(0)
})

test('no orbit while the user is interacting', async ({ page }) => {
  await open(page, 'no-preference')
  const doors = (await kindIds(page, 'door')).slice(0, 3)
  const box = (await page.getByLabel('3D building model', { exact: true }).boundingBox())!
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.down(); await page.mouse.move(box.x + box.width / 2 + 40, box.y + box.height / 2 + 10); await page.mouse.up()
  const state = await page.evaluate((ids) => { const v = (window as Win).viewer3dTest; v.highlight(ids, { cinematic: true }); return v.getCinematicState() }, doors)
  expect(state.active).toBe(true)
  expect(state.orbit).toBe(false)
  expect(state.angle).toBeNull()
})

test('reduced motion shows the lit answer at once', async ({ page }) => {
  await open(page, 'reduce')
  const doors = (await kindIds(page, 'door')).slice(0, 4)
  const result = await page.evaluate((ids) => {
    const v = (window as Win).viewer3dTest
    v.highlight(ids, { cinematic: true })
    let glow = -1
    v.scene!.items.get(ids[0])!.traverse((n) => { const m = (n as { material?: { emissiveIntensity?: number } }).material; if (m && !Array.isArray(m) && m.emissiveIntensity !== undefined) glow = m.emissiveIntensity })
    return { state: v.getCinematicState(), glow }
  }, doors)
  expect(result.state.active).toBe(false)
  expect(result.glow).toBe(2.8)
})

test('hide fades out, reset fades back in, isolate dims the rest gradually', async ({ page }) => {
  await open(page, 'no-preference')
  const windows = (await kindIds(page, 'window')).slice(0, 4)
  const doors = (await kindIds(page, 'door')).slice(0, 2)
  const hide = await page.evaluate((ids) => { const v = (window as Win).viewer3dTest; v.applyCommand({ op: 'hide', item_ids: ids }); return ids.map((id) => v.scene!.items.get(id)!.visible) }, windows)
  expect(hide).toEqual(windows.map(() => true)) // still visible at the first frame: it fades
  await expect.poll(() => page.evaluate((ids) => ids.every((id) => !(window as Win).viewer3dTest.scene!.items.get(id)!.visible), windows)).toBe(true)
  await page.evaluate(() => (window as Win).viewer3dTest.applyCommand({ op: 'reset', item_ids: [] }))
  await expect.poll(() => page.evaluate((ids) => ids.every((id) => (window as Win).viewer3dTest.scene!.items.get(id)!.visible), windows)).toBe(true)
  const wall = (await kindIds(page, 'wall'))[0]
  const opacityOf = (id: string) => page.evaluate((item) => { let o = 1; (window as Win).viewer3dTest.scene!.items.get(item)!.traverse((n) => { const m = (n as { material?: { opacity: number } }).material; if (m && !Array.isArray(m)) o = Math.min(o, m.opacity) }); return o }, id)
  await page.evaluate((ids) => (window as Win).viewer3dTest.applyCommand({ op: 'isolate', item_ids: ids }), doors)
  expect(await opacityOf(wall)).toBeGreaterThan(0.9) // starts at full opacity, no snap
  await expect.poll(() => opacityOf(wall)).toBeLessThan(0.25)
  await page.evaluate(() => (window as Win).viewer3dTest.applyCommand({ op: 'reset', item_ids: [] }))
  await expect.poll(() => opacityOf(wall)).toBe(1)
})

test('Visualise it re-opens 3D after toggling back to 2D', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/#/chat')
  const composer = page.getByRole('combobox', { name: 'Ask about your drawings' })
  await composer.fill('@colorful-11397')
  await page.getByRole('option').filter({ hasText: 'colorful-11397' }).click()
  await composer.fill('How many windows are there?')
  await page.getByRole('button', { name: 'Send question', exact: true }).click()
  const toggle = page.getByRole('group', { name: 'Viewer mode' })
  const visualise = page.getByRole('button', { name: 'Visualise it', exact: true }).first()
  await visualise.click({ timeout: 90_000 })
  await expect(toggle.getByRole('button', { name: '3D', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await toggle.getByRole('button', { name: '2D', exact: true }).click()
  await expect(toggle.getByRole('button', { name: '2D', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await visualise.click()
  await expect(toggle.getByRole('button', { name: '3D', exact: true })).toHaveAttribute('aria-pressed', 'true')
})
