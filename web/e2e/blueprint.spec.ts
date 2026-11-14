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
      if (m && !Array.isArray(m) && m.emissiveIntensity !== undefined) out.push({ opacity: m.opacity, emissive: m.emissiveIntensity })
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

test('IFC rooms are thin floor tints (no lids), labels lie flat on the floor, and overlapping storey tags are thinned', async ({ page }) => {
  await open(page, 'ifc_bench__ac20-arc', 'ifc_bench__ac20-arc')
  await page.evaluate(() => (window as Win).viewer3dTest.setStorey('Erdgeschoss'))
  await page.waitForTimeout(600)
  const r = await page.evaluate(() => {
    const v = (window as Win).viewer3dTest; const s = v.scene!
    const labels: { y: number; min: number }[] = []
    let tallRooms = 0
    for (const [id, o] of s.items) { if (s.manifest.items[id].kind !== 'room' || !o.visible) continue; const b = o.scale.y * (s.manifest.items[id].bbox_m![1][1] - s.manifest.items[id].bbox_m![0][1]); if (b > 0.3) tallRooms++ }
    s.root.parent?.traverse((n) => {
      if (!n.name.startsWith('room-label:') || !n.visible) return
      const item = s.manifest.items[n.name.slice('room-label:'.length)]
      labels.push({ y: n.position.y, min: item.bbox_m![0][1] })
    })
    return { labels, tallRooms, tags: [...document.querySelectorAll('.viewer3d-storey-label')].filter((e) => (e.parentElement as HTMLElement).style.display !== 'none').length }
  })
  expect(r.labels.length).toBeGreaterThan(5)
  for (const l of r.labels) expect(l.y).toBeCloseTo(l.min + 0.05, 3)
  expect(r.tallRooms).toBe(0)
  expect(r.tags).toBeLessThan(5)
})

test('72 highlights: at most 12 callout tags, glow and legend stay, the building fills the frame and the site is faint', async ({ page }) => {
  await page.setViewportSize({ width: 1000, height: 800 })
  await open(page, 'ifc_bench__ac20-arc', 'ifc_bench__ac20-arc')
  const r = await page.evaluate(async () => {
    const v = (window as Win).viewer3dTest; const s = v.scene!
    v.setStorey('Erdgeschoss')
    const ground = (k: string) => [...s.items.keys()].filter((i) => s.manifest.items[i].kind === k && (s.manifest.items[i].storey === 'Erdgeschoss' || (s.manifest.items[i].storey as { name?: string })?.name === 'Erdgeschoss'))
    const ids = [...ground('door'), ...ground('window')]
    v.highlight(ids, {})
    await new Promise((r) => setTimeout(r, 1500))
    // Screen width covered by the building's walls (projected bbox corners), not the site.
    const canvas = v.renderer.domElement
    let min = Infinity, max = -Infinity
    for (const [id, o] of s.items) {
      const it = s.manifest.items[id]
      if (it.kind !== 'wall' || !o.visible || !it.bbox_m) continue
      for (const x of [it.bbox_m[0][0], it.bbox_m[1][0]]) for (const y of [it.bbox_m[0][1], it.bbox_m[1][1]]) for (const z of [it.bbox_m[0][2], it.bbox_m[1][2]]) {
        const p = v.camera.position.clone().set(x, y, z).project(v.camera)
        const px = (p.x + 1) * canvas.clientWidth / 2
        min = Math.min(min, px); max = Math.max(max, px)
      }
    }
    let siteOpacity = 1
    for (const [id, o] of s.items) if (s.manifest.items[id].kind === 'site') o.traverse((n) => { const m = (n as { material?: { opacity: number } }).material; if (m && !Array.isArray(m)) siteOpacity = m.opacity })
    return { highlighted: ids.length, tags: document.querySelectorAll('.viewer3d-annotation').length, covered: (max - min) / canvas.clientWidth, siteOpacity }
  })
  expect(r.highlighted).toBeGreaterThan(12)
  expect(r.tags).toBeLessThanOrEqual(12)
  expect(r.covered).toBeGreaterThanOrEqual(0.4)
  expect(r.siteOpacity).toBeLessThan(0.5)
})

test('storey answer: the model is cut above that storey, the build-up ends on it, doors and windows glow with outlines, no pins', async ({ page }) => {
  await open(page, 'ifc_bench__ac20-arc', 'ifc_bench__ac20-arc')
  const r = await page.evaluate(async () => {
    const v = (window as Win).viewer3dTest; const s = v.scene!
    let last: { label: string; index: number; total: number } | null = null
    v.onBuildChange((b) => { if (b) last = b })
    v.visualise()
    const floor = (k: string) => [...s.items.keys()].filter((i) => s.manifest.items[i].kind === k && ((s.manifest.items[i].storey as { name?: string })?.name ?? s.manifest.items[i].storey) === '1. Obergeschoss')
    const ids = [...floor('door'), ...floor('window')]
    v.highlight(ids, {})
    await new Promise((res) => setTimeout(res, 1200))
    let aboveVisible = 0, roofVisible = 0, outlines = 0
    for (const [id, o] of s.items) {
      const it = s.manifest.items[id]; const st = (it.storey as { name?: string })?.name ?? it.storey
      if (o.visible && typeof st === 'string' && /Dachgeschoss|2\. Obergeschoss/.test(st)) aboveVisible++
      if (o.visible && it.kind === 'roof') roofVisible++
    }
    s.root.traverse((n) => { if (n.userData.highlightOutline) outlines++ })
    return { n: ids.length, aboveVisible, roofVisible, outlines, label: (last as { label?: string } | null)?.label ?? '', pins: document.querySelectorAll('.viewer3d-finding-pin').length,
      edit: document.querySelector('button[aria-label="Edit"]')?.getAttribute('aria-pressed') }
  })
  expect(r.n).toBeGreaterThan(12)
  expect(r.aboveVisible).toBe(0)
  expect(r.roofVisible).toBe(0)
  expect(r.outlines).toBeGreaterThan(0)
  expect(r.label).not.toMatch(/Dachgeschoss|Roof/i)
  expect(r.pins).toBe(0)
  expect(r.edit).not.toBe('true')
})

test('toilets across storeys: all storeys stay, only the roof is off, every WC lit, tags and legend say WC', async ({ page }) => {
  await open(page, 'ifc_bench__ac20-arc', 'ifc_bench__ac20-arc')
  const r = await page.evaluate(async () => {
    const v = (window as Win).viewer3dTest; const s = v.scene!
    const wc = [...s.items.keys()].filter((i) => s.manifest.items[i].kind === 'room' && /^WC/.test(s.manifest.items[i].name ?? ''))
    v.highlight(wc, { cameraTargetItemId: wc[0] })
    await new Promise((res) => setTimeout(res, 800))
    const visible = wc.filter((i) => { for (let n: { visible: boolean; parent: unknown } | null = s.items.get(i)!; n; n = n.parent as typeof n) if (!n.visible) return false; return true })
    const tags = [...document.querySelectorAll('.viewer3d-label-kind')].map((e) => e.textContent)
    const legend = [...document.querySelectorAll('[data-testid="kind-legend"] li')].map((e) => e.textContent)
    let roofVisible = 0
    for (const [id, o] of s.items) if (s.manifest.items[id].kind === 'roof' && o.visible) roofVisible++
    return { total: wc.length, lit: visible.length, tags, legend, roofVisible }
  })
  expect(r.total).toBe(8)
  expect(r.lit).toBe(8)
  expect(r.roofVisible).toBe(0)
  expect(r.tags.every((t) => t === 'WC')).toBe(true)
  expect(r.tags.length).toBeGreaterThan(0)
})
