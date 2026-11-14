import { expect, test } from '@playwright/test'
import type { LinkedViewerCanvas } from '../src/viewer3d/Viewer3D'

// X-24: opened from an answer, the answer's items are visible from the first frame of the build-up, and the storey
// selector agrees with the step label while it plays.
test.setTimeout(120_000)
const docId = 'ifc_bench__ac20-arc'
test('3D from an answer: highlights built from the first frame; selector follows the build step', async ({ page, request }, testInfo) => {
  const { id } = await (await request.post('http://localhost:8000/api/chats', { data: { doc_ids: [docId], title: 'X-24 3D' } })).json() as { id: string }
  const first = await request.post(`http://localhost:8000/api/chats/${id}/messages`, { data: { doc_ids: [docId], content: 'How many doors are there?' }, timeout: 60_000 })
  await first.text()
  await page.addInitScript(() => {
    const w = window as unknown as { __log: { t: number; hi: number; built: number; storey: string | null; step: string }[] }
    w.__log = []
    const tick = () => {
      const h = (document.querySelector('.drawing-model canvas') as LinkedViewerCanvas | null)?.__viewer3d
      if (h) {
        const ids = h.state().highlighted
        w.__log.push({ t: performance.now(), hi: ids.length, built: ids.filter((i) => (h.scaleY(i) ?? 0) > 0.99).length, ...h.storeyAndStep() })
      }
      requestAnimationFrame(tick)
    }
    requestAnimationFrame(tick)
  })
  await page.goto(`/?viewer3dTest=1#/chat?chat=${encodeURIComponent(id)}`)
  await page.getByRole('button', { name: /^Open citation/ }).first().click()
  const viewer = page.getByRole('region', { name: 'Drawing viewer', exact: true })
  await viewer.locator('.viewer3d-visualise-button').click()
  await expect(viewer.getByRole('region', { name: '3D viewer', exact: true })).toHaveAttribute('data-state', 'ready', { timeout: 90_000 })
  await expect(page.locator('.drawing-model')).toHaveAttribute('data-rise-state', 'done', { timeout: 90_000 })
  const log = await page.evaluate(() => (window as unknown as { __log: { t: number; hi: number; built: number; storey: string | null; step: string }[] }).__log)
  const withHi = log.filter((e) => e.hi > 0)
  const hidden = withHi.filter((e) => e.built < e.hi)
  const playing = (e: { step: string }) => { const m = /Step (\d+) of (\d+)/.exec(e.step); return !!m && m[1] !== m[2] }
  const mismatched = log.filter((e) => playing(e) && e.step && e.storey && !e.step.includes(`· ${e.storey} `) && !e.step.includes('· Roof') && !e.step.includes('Foundations'))
  console.log('frames', log.length, 'withHighlights', withHi.length, 'hiddenFrames', hidden.length, 'mismatch', mismatched.length, JSON.stringify(mismatched.slice(0, 2)))
  expect(withHi.length).toBeGreaterThan(5)
  expect(hidden.length).toBe(0)
  expect(mismatched.length).toBe(0)
})

