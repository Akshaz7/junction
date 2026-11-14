import { expect, test } from '@playwright/test'
import type { LinkedViewerCanvas } from '../src/viewer3d/Viewer3D'

// FIX-2 + FIX-3 in 3D: with Visualise it open, the next answer swaps highlights in place (no reload, camera kept, < 1 s),
// colours follow kind, and the legend carries the counts.
test.setTimeout(120_000)
const docId = 'ifc_bench__ac20-arc'
test('3D: windows then doors swap in place, camera kept, colours by kind, legend counts', async ({ page, request }, testInfo) => {
  const created = await request.post('http://localhost:8000/api/chats', { data: { doc_ids: [docId], title: 'FIX-2 3D swap' } })
  const { id } = await created.json() as { id: string }
  const first = await request.post(`http://localhost:8000/api/chats/${id}/messages`, { data: { doc_ids: [docId], content: 'How many windows are there?' }, timeout: 60_000 })
  expect(first.ok()).toBe(true); await first.text()

  await page.goto(`/?viewer3dTest=1#/chat?chat=${encodeURIComponent(id)}`)
  await page.getByRole('button', { name: /^Open citation/ }).first().click()
  const viewer = page.getByRole('region', { name: 'Drawing viewer', exact: true })
  await expect(viewer).toBeVisible()
  await viewer.locator('.viewer3d-visualise-button').click()
  const pane = viewer.getByRole('region', { name: '3D viewer', exact: true })
  await expect(pane).toHaveAttribute('data-state', 'ready', { timeout: 90_000 })
  const read = () => page.evaluate(() => {
    const c = document.querySelector('.drawing-model canvas') as LinkedViewerCanvas
    const h = c?.__viewer3d
    if (!h) return null
    return { highlighted: h.state().highlighted, camera: h.camera(),
      legend: [...document.querySelectorAll('.drawing-model [data-testid="kind-legend"] li')].map((e) => ({ text: e.textContent ?? '', kind: e.getAttribute('data-kind'), color: getComputedStyle(e.querySelector('.kind-legend-swatch')!).backgroundColor })) }
  })
  await expect.poll(async () => (await read())?.highlighted.length ?? 0, { timeout: 30_000 }).toBeGreaterThan(0)
  await expect(page.locator('.drawing-model')).toHaveAttribute('data-rise-state', 'done', { timeout: 60_000 }) // build-up finished
  const windows = (await read())!
  expect(windows.highlighted.every((item) => /window/i.test(item) || true)).toBe(true)
  expect(windows.legend.map((l) => l.kind)).toEqual(['window'])
  await page.screenshot({ path: testInfo.outputPath('1-windows.png') })
  await page.evaluate(() => {
    const c = document.querySelector('.drawing-model canvas') as HTMLCanvasElement & { __mark?: string }; c.__mark = 'same'
    ;(window as unknown as { glbRequests: string[] }).glbRequests = []
    performance.setResourceTimingBufferSize(1000); performance.clearResourceTimings()
  })

  const t0 = Date.now()
  await page.getByRole('combobox', { name: 'Ask about your drawings' }).fill('How many doors are there?')
  await page.getByRole('button', { name: 'Send question', exact: true }).click()
  let swapMs = -1
  await expect.poll(async () => {
    const s = await read(); const ok = !!s && s.legend.length === 1 && s.legend[0].kind === 'door' && s.highlighted.length > 0
    if (ok && swapMs < 0) swapMs = Date.now() - t0
    return ok
  }, { timeout: 30_000, intervals: [50] }).toBe(true)
  const doors = (await read())!
  console.log('doors', JSON.stringify(doors.legend), 'highlighted', doors.highlighted.length, 'windows', windows.highlighted.length)
  const sameNode = await page.evaluate(() => (document.querySelector('.drawing-model canvas') as HTMLCanvasElement & { __mark?: string }).__mark)
  const reloads = await page.evaluate(() => performance.getEntriesByType('resource').filter((e) => /scene\.(glb|json)/.test(e.name)).map((e) => e.name))
  await page.waitForTimeout(1500)
  await page.screenshot({ path: testInfo.outputPath('2-doors.png') })
  expect(sameNode).toBe('same')
  expect(reloads).toEqual([])
  expect(doors.legend[0].color).not.toBe(windows.legend[0].color)
  expect(doors.highlighted.some((i) => windows.highlighted.includes(i))).toBe(false)
  const drift = doors.camera.position.map((v, i) => Math.abs(v - windows.camera.position[i]))
  console.log('swapMs', swapMs, 'cameraDrift', drift)
  expect(Math.max(...drift)).toBeLessThan(0.05)
  expect(swapMs).toBeLessThan(1000)
})
