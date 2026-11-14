import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, test, type Page } from '@playwright/test'
import type { Viewer } from '../src/viewer3d/viewer'

// Blueprint layer: flat room labels, per-kind materials, overall dimensions, storey tags. The local API and fixtures still serve
// pre-S-21 manifests (no room names/areas), so the backfilled deploy manifest is served for the scene request;
// the GLB comes from the live API (IFC) or the fixture (raster).
test.setTimeout(120_000)
test.use({ reducedMotion: 'reduce' })
type Win = typeof window & { viewer3dTest: Viewer }

const manifest = (doc: string) => readFileSync(resolve(process.cwd(), `../deploy/demo_artifacts/${doc}/scene.json`), 'utf8')

async function open(page: Page, query: string, doc: string) {
  const serve = (route: { fulfill(o: { contentType: string; body: string }): Promise<void> }) => route.fulfill({ contentType: 'application/json', body: manifest(doc) })
  await page.route(/\/api\/docs\/[^/]+\/(scene|files\/scene\.json)$/, serve)
  await page.route('**/fixtures/colorful-11397/scene.json', serve)
  await page.goto(`/?doc=${query}&viewer3dTest=1#/viewer-test`)
  await expect(page.getByRole('region', { name: '3D viewer', exact: true }).first()).toHaveAttribute('data-state', 'ready', { timeout: 90_000 })
  await expect.poll(() => page.evaluate(() => Boolean((window as Win).viewer3dTest?.getBlueprintState()))).toBe(true)
}
const state = (page: Page) => page.evaluate(() => (window as Win).viewer3dTest.getBlueprintState()!)

test('raster plan: room names and areas lie flat, small rooms hide, wet rooms tint blue', async ({ page }) => {
  await open(page, 'colorful-11397', 'cubicasa5k__colorful-11397')
  await page.waitForTimeout(400)
  const bp = await state(page)
  const shown = bp.rooms.filter((r) => r.shown)
  expect(shown.length).toBeGreaterThan(2)
  expect(bp.rooms.some((r) => r.hidden === 'small')).toBe(true) // the 0.6 m2 storage closet
  expect(shown.every((r) => r.name || r.area)).toBe(true)
  expect(shown.some((r) => r.area && /^\d+\.\d m²$/.test(r.area))).toBe(true)
  expect(bp.materials.window).toBe('#9fd3ea')
  expect(bp.materials.door).toBe('#9c6b3c')
  const flat = await page.evaluate(() => {
    const scene = (window as Win).viewer3dTest.scene!
    let count = 0
    scene.root.parent?.traverse((n) => { if (n.name.startsWith('room-label:') && n.visible && Math.abs(n.rotation.x + Math.PI / 2) < 1e-6) count++ })
    return count
  })
  expect(flat).toBe(shown.length)
})

test('per-kind materials: glass windows, wood doors, darker cut-top walls', async ({ page }) => {
  await open(page, 'colorful-11397', 'cubicasa5k__colorful-11397')
  const mats = await page.evaluate(() => {
    const scene = (window as Win).viewer3dTest.scene!
    const first = (kind: string) => {
      const id = [...scene.items.keys()].find((i) => scene.manifest.items[i].kind === kind)!
      type Mat = { color?: { getHexString(): string }; opacity: number; transparent: boolean }
      const found: Mat[] = []
      scene.items.get(id)!.traverse((n) => { const m = (n as { material?: unknown }).material; if (!found.length && m && !Array.isArray(m)) found.push(m as Mat) })
      return { color: found[0]?.color?.getHexString(), opacity: found[0]?.opacity ?? 1, transparent: found[0]?.transparent ?? false }
    }
    return { window: first('window'), door: first('door'), wall: first('wall') }
  })
  expect(mats.window).toMatchObject({ color: '9fd3ea', transparent: true })
  expect(mats.window.opacity).toBeLessThan(0.6)
  expect(mats.door.color).toBe('9c6b3c')
  expect(mats.wall.color).toBe('d9d4c9')
})

test('overall dimensions and storey label with elevation', async ({ page }) => {
  await open(page, 'colorful-11397', 'cubicasa5k__colorful-11397')
  await page.waitForTimeout(400)
  const bp = await state(page)
  expect(bp.dimensions).toHaveLength(2)
  expect(bp.dimensions.every((d) => /^\d+\.\d m$/.test(d))).toBe(true)
  await expect(page.locator('.viewer3d-dim-label')).toHaveCount(2)
  await expect(page.locator('.viewer3d-storey-label')).toHaveText('Floor 1 · +0.00 m')
})

test('answer highlights still pop over glass and tinted materials', async ({ page }) => {
  await open(page, 'colorful-11397', 'cubicasa5k__colorful-11397')
  const lit = await page.evaluate(async () => {
    const viewer = (window as Win).viewer3dTest
    const ids = [...viewer.scene!.items.keys()].filter((i) => viewer.scene!.manifest.items[i].kind === 'window').slice(0, 2)
    viewer.highlight(ids, {})
    await new Promise((r) => setTimeout(r, 600))
    const out: { opacity: number; emissive: number }[] = []
    for (const id of ids) viewer.scene!.items.get(id)!.traverse((n) => {
      const m = (n as { material?: { opacity: number; emissiveIntensity?: number } }).material
      if (m && !Array.isArray(m)) out.push({ opacity: m.opacity, emissive: m.emissiveIntensity ?? 0 })
    })
    return out
  })
  expect(lit.length).toBeGreaterThan(0)
  for (const m of lit) { expect(m.opacity).toBeGreaterThanOrEqual(0.9); expect(m.emissive).toBeGreaterThan(1) }
})

test('IFC model: every storey gets a name and elevation tag, rooms carry names and areas', async ({ page }) => {
  await open(page, 'ifc_bench__ac20-arc', 'ifc_bench__ac20-arc')
  await page.waitForTimeout(500)
  const bp = await state(page)
  expect(bp.storeys.map((s) => s.label)).toEqual(expect.arrayContaining(['Erdgeschoss · +0.00 m', 'Keller · −3.00 m']))
  expect(bp.rooms.filter((r) => r.name && r.area).length).toBeGreaterThan(10)
  expect(bp.dimensions).toHaveLength(2)
})
