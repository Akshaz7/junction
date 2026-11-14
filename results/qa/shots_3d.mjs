// R3D: headless screenshots of "Visualise it" for raster docs. One browser, local web :5173 (proxies to the local API :8000).
// Usage: node results/qa/shots_3d.mjs [tag]   -> results/qa/shots/r3d-<doc>.png (tag adds a suffix, e.g. "after")
import { createRequire } from 'node:module'
import { mkdirSync, existsSync } from 'node:fs'
const require = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = require('@playwright/test')
const tag = process.argv[2] ? `-${process.argv[2]}` : ''
const BASE = process.env.WEB || 'http://localhost:5173'
const DOCS = ['cubicasa5k__high-quality-10306', 'cubicasa5k__colorful-11397', 'cubicasa5k__colorful-11400', 'cubicasa5k__colorful-11960', 'cubicasa5k__colorful-12200',
  'uploads__v13-bolduc', 'uploads__v13-canada-cement', 'uploads__v13-home-plan-1921', 'uploads__v13-simon-house', 'uploads__v13-toorak-residence']
mkdirSync(new URL('./shots/', import.meta.url), { recursive: true })
const browser = await chromium.launch({ channel: 'chromium', args: ['--use-angle=metal', '--ignore-gpu-blocklist', '--enable-gpu'] })
const grouped = await (await fetch(`${BASE}/api/docs`)).json()
const have = new Map(grouped.sources.flatMap((s) => s.docs).map((d) => [d.doc_id, d]))
const rows = []
for (const id of DOCS) {
  const out = new URL(`./shots/r3d-${id}${tag}.png`, import.meta.url).pathname
  const doc = have.get(id)
  if (!doc) { rows.push(`${id}: not local (not in /api/docs)`); continue }
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce' })   // fresh state per doc
  const page = await ctx.newPage()
  try {
    await page.goto(`${BASE}/#/data`)
    await page.getByRole('searchbox', { name: 'Search documents' }).fill(id)
    await page.locator(`.data-file-row[data-doc-id="${id}"]`).waitFor({ timeout: 15_000 })
    await page.locator(`.data-file-row[data-doc-id="${id}"]`).getByRole('button', { name: `Open ${doc.title}`, exact: true }).click()
    const detail = page.locator('aside.data-detail')
    await detail.getByRole('button', { name: 'Visualise it', exact: true }).click({ timeout: 10_000 })
    const viewer = page.getByRole('region', { name: '3D viewer', exact: true })
    await viewer.waitFor({ timeout: 15_000 })
    await page.waitForFunction(() => document.querySelector('[aria-label="3D viewer"]')?.getAttribute('data-state') === 'ready', null, { timeout: 60_000 })
    await page.waitForTimeout(2500)
    await page.screenshot({ path: out })
    rows.push(`${id}: ok -> ${out}`)
  } catch (e) {
    await page.screenshot({ path: out }).catch(() => {})
    rows.push(`${id}: FAILED ${String(e.message).split('\n')[0]} -> ${out}`)
  }
  await ctx.close()
}
await browser.close()
console.log(rows.join('\n'))
