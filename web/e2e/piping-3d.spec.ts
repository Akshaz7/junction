import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, test } from '@playwright/test'
import type { Viewer } from '../src/viewer3d/viewer'

// W-64: plumbing IFCs open in Visualise it; pipes, drains and fittings have their own colours and legend entries; GlobalId
// highlights glow; pipe size groups show; a 22k-item scene keeps its frame rate. The served manifests carry no system or
// dn yet, so the test merges them from results/vision/piping (what the backfill will write into props).
test.setTimeout(180_000)
test.use({ reducedMotion: 'reduce', channel: 'chromium', launchOptions: { args: ['--use-angle=metal', '--ignore-gpu-blocklist', '--enable-gpu'] } })
type Win = typeof window & { viewer3dTest: Viewer }
const root = (p: string) => resolve(process.cwd(), '..', p)

for (const doc of ['ifc_bench__digital-hub-plumbing', 'ifc_bench__sixty5-plumbing']) {
  test(`${doc}: pipes, drains and sizes light up and stay fast`, async ({ page }) => {
    const scene = JSON.parse(readFileSync(root(`artifacts/${doc}/scene.json`), 'utf8'))
    const piping = JSON.parse(readFileSync(root(`results/vision/piping/${doc}.json`), 'utf8')).pipes as { item_id: string; dn_mm: number | null; system: string | null; name: string }[]
    const byId = new Map(piping.map((p) => [p.item_id, p]))
    for (const [id, item] of Object.entries<{ kind: string; props?: Record<string, unknown> }>(scene.items)) {
      const p = byId.get(id)
      if (p) item.props = { system: p.system, dn_mm: p.dn_mm, type_name: p.name }
    }
    await page.route(/\/api\/docs\/[^/]+\/(scene|files\/scene\.json)$/, (route) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(scene) }))
    await page.goto(`/?doc=${doc}&viewer3dTest=1#/viewer-test`)
    await expect(page.getByRole('region', { name: '3D viewer', exact: true }).first()).toHaveAttribute('data-state', 'ready', { timeout: 120_000 })
    const r = await page.evaluate(async () => {
      const v = (window as Win).viewer3dTest; const s = v.scene!
      const items = s.manifest.items
      const all = [...s.items.keys()].filter((i) => items[i].kind === 'pipe')
      const drainIds = all.filter((i) => /abwasser|schmutz/i.test(String(items[i].props?.system ?? '')))
      const pipes = [...drainIds.slice(0, 100), ...all.filter((i) => !drainIds.includes(i)).slice(0, 200)]
      const fittings = [...s.items.keys()].filter((i) => items[i].kind === 'pipe_fitting').slice(0, 50)
      v.highlight([...pipes, ...fittings], {})
      await new Promise((res) => setTimeout(res, 1000))
      const lit = [...pipes, ...fittings].filter((i) => { let n = false; s.items.get(i)?.traverse((o) => { const m = (o as { material?: { emissiveIntensity?: number } }).material; if (m && (m.emissiveIntensity ?? 0) > 1) n = true }); return n })
      const legend = [...document.querySelectorAll('[data-testid="kind-legend"] li')].map((e) => e.textContent ?? '')
      v.resetPerf()
      const t0 = performance.now(); const target = v.controls.target.clone(); const off = v.camera.position.clone().sub(target)
      await new Promise<void>((done) => { const f = (now: number) => { const a = Math.min(1, (now - t0) / 3000) * Math.PI * 2
        v.camera.position.copy(target).add(off.clone().set(off.x * Math.cos(a) + off.z * Math.sin(a), off.y, off.z * Math.cos(a) - off.x * Math.sin(a))); v.controls.update()
        now - t0 < 3000 ? requestAnimationFrame(f) : done() }; requestAnimationFrame(f) })
      return { total: pipes.length + fittings.length, lit: lit.length, legend, perf: v.perf() }
    })
    console.log(doc, JSON.stringify(r))
    expect(r.lit).toBe(r.total)
    expect(r.legend.some((t) => /pipes/i.test(t))).toBe(true)
    if (doc.includes('digital-hub')) expect(r.legend.some((t) => /^Drains/i.test(t))).toBe(true)
    expect(r.legend.some((t) => /DN\d+/.test(t))).toBe(true)
    expect(r.legend.some((t) => /fitting/i.test(t))).toBe(true)
    expect(r.perf.p95_ms).toBeLessThan(33)
  })
}
