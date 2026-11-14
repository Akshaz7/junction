import { expect, test } from '@playwright/test'
import type { LinkedViewerCanvas } from '../src/viewer3d/Viewer3D'

// Demo flow, 3D steps on AC20: doors+windows -> Visualise -> toilets -> remove the front door -> reset. Screenshots per step.
test.setTimeout(240_000)
const docId = 'ifc_bench__ac20-arc'
test('demo 3D flow screenshots', async ({ page, request }, testInfo) => {
  const { id } = await (await request.post('http://localhost:8000/api/chats', { data: { doc_ids: [docId], title: 'demo 3D' } })).json() as { id: string }
  const first = await request.post(`http://localhost:8000/api/chats/${id}/messages`, { data: { doc_ids: [docId], content: 'How many doors and windows are there?' }, timeout: 60_000 })
  await first.text()
  await page.goto(`/?viewer3dTest=1#/chat?chat=${encodeURIComponent(id)}`)
  await page.getByRole('button', { name: /^Open citation/ }).first().click()
  const viewer = page.getByRole('region', { name: 'Drawing viewer', exact: true })
  await viewer.locator('.viewer3d-visualise-button').click()
  await expect(page.locator('.drawing-model')).toHaveAttribute('data-rise-state', 'done', { timeout: 90_000 })
  const info = () => page.evaluate(() => {
    const h = (document.querySelector('.drawing-model canvas') as LinkedViewerCanvas).__viewer3d!
    const cs = h.commandState() as unknown as Record<string, unknown>; return { cs: JSON.stringify(cs).slice(0, 200), ids: h.state().highlighted, cam: h.camera(), lit: h.state().highlighted.length, tags: document.querySelectorAll('.drawing-model .viewer3d-annotation').length,
      legend: [...document.querySelectorAll('.drawing-model [data-testid="kind-legend"] li')].map((e) => e.textContent), ...h.storeyAndStep() }
  })
  const shot = async (name: string) => { await page.waitForTimeout(2500); console.log(name, JSON.stringify(await info())); await page.screenshot({ path: testInfo.outputPath(`${name}.png`) }) }
  await shot('1-doors-windows')
  const ask = async (q: string) => {
    await page.getByRole('combobox', { name: 'Ask about your drawings' }).fill(q)
    await page.getByRole('button', { name: 'Send question', exact: true }).click()
    await expect(page.locator('.question-bubble').filter({ hasText: q }).last()).toBeVisible()
  }
  await ask('Where are the toilets?'); await page.waitForTimeout(4000); await shot('2-toilets')
  await ask('remove the front door'); await page.waitForTimeout(4000); await shot('3-remove-front-door')
  await ask('reset'); await page.waitForTimeout(4000); await shot('4-reset')
})
