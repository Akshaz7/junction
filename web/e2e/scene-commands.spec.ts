import { expect, test, type Page } from '@playwright/test'
import type { Answer } from '../src/lib/types'
import type { LinkedViewerCanvas } from '../src/viewer3d/Viewer3D'
import { streamedAnswer } from './streamed-answer'

const api = 'http://localhost:8000'
const docId = 'ifc_bench__ac20-arc'
test.setTimeout(60_000)

async function openChat(page: Page, id: string) {
  let snapshots = 0
  page.on('response', (response) => {
    if (response.ok() && new URL(response.url()).pathname === `/api/chats/${id}`) snapshots++
  })
  await page.goto(`/?viewer3dTest=1#/chat?chat=${id}`)
  await expect(page.getByText('Connected workspace', { exact: true })).toBeVisible()
  await expect.poll(() => snapshots).toBeGreaterThanOrEqual(2)
  await expect(page.getByRole('combobox', { name: 'Ask about your drawings' })).toBeEnabled()
}

async function send(page: Page, text: string) {
  await page.getByRole('combobox', { name: 'Ask about your drawings' }).fill(text)
  const response = page.waitForResponse((res) => res.request().method() === 'POST' && /\/api\/chats\/[^/]+\/messages$/.test(new URL(res.url()).pathname))
  await page.getByRole('button', { name: 'Send question', exact: true }).click()
  const answer = await streamedAnswer(await response)
  expect(answer.answer.abstained).toBe(false)
  expect(answer.trace.some((step) => step.stub)).toBe(false)
  return answer
}

async function openTaggedDrawingAndModel(page: Page, itemId: string) {
  const chip = page.locator('.scene-tag').filter({ has: page.getByText('W3', { exact: true }) }).first()
  await chip.click()
  const box = page.locator(`.evidence-region[data-item-id="${itemId}"]`)
  await expect(box).toBeVisible()
  await expect(box.locator('text')).toHaveText('W3')
  await page.getByRole('button', { name: 'Visualise it', exact: true }).click()
  const model = page.getByRole('dialog', { name: 'Visualise it', exact: true })
  await expect(model.getByRole('region', { name: '3D viewer', exact: true })).toHaveAttribute('data-state', 'ready', { timeout: 25_000 })
  const drawing = page.getByRole('region', { name: 'Drawing viewer', exact: true })
  const panelBounds = await model.boundingBox(), drawingBounds = await drawing.boundingBox()
  expect(panelBounds).toBeTruthy()
  expect(drawingBounds).toBeTruthy()
  expect(panelBounds!.x).toBeGreaterThanOrEqual(drawingBounds!.x)
  expect(panelBounds!.x + panelBounds!.width).toBeLessThanOrEqual(drawingBounds!.x + drawingBounds!.width)
  await page.getByRole('combobox', { name: 'Ask about your drawings' }).click()
  return { box, model }
}

async function hiddenInModel(page: Page, id: string) {
  return page.getByRole('dialog', { name: 'Visualise it', exact: true }).locator('canvas').evaluate((node: LinkedViewerCanvas, itemId) => {
    if (!node.__viewer3d) throw new Error('Viewer test handle is not ready')
    return node.__viewer3d.commandState().hidden.includes(itemId)
  }, id)
}

test('real window commands, 2D tags, 3D and Undo stay in sync on two devices', async ({ page, browser, request, baseURL }) => {
  const created = await request.post(`${api}/api/chats`, { data: { doc_ids: [docId], title: 'Scene commands verification' } })
  expect(created.ok()).toBe(true)
  const { id } = await created.json() as { id: string }
  await openChat(page, id)
  const shown: Answer = await send(page, 'show me all the windows')
  const command = shown.evidence.scene.commands?.find((entry) => entry.op === 'highlight')
  expect(command, 'Real API must return the window highlight command').toBeTruthy()
  const itemId = Object.entries(command!.labels ?? {}).find(([, tag]) => tag === 'W3')?.[0]
  expect(itemId, 'W3 must be a real stable tag from the API').toBeTruthy()
  const tags = page.getByLabel('Scene command items').first()
  await expect(tags).toHaveAttribute('data-item-count', String(command!.item_ids.length))
  if (command!.item_ids.length > 12) await tags.getByRole('button', { name: /^\+\d+ more$/ }).click()
  await expect(tags.locator('.scene-tag')).toHaveCount(command!.item_ids.length)
  expect((await tags.locator('.scene-tag > span').allTextContents()).sort()).toEqual(Object.values(command!.labels!).sort())
  const a = await openTaggedDrawingAndModel(page, itemId!)
  const context = await browser.newContext({ baseURL })
  try {
    const other = await context.newPage()
    await openChat(other, id)
    const b = await openTaggedDrawingAndModel(other, itemId!)
    const start = performance.now()
    const hidden = await send(page, 'remove window W3')
    expect(hidden.evidence.scene.commands).toContainEqual(expect.objectContaining({ op: 'hide', item_ids: [itemId] }))
    for (const target of [page, other]) {
      await expect(target.locator(`.scene-tag[data-item-id="${itemId}"]`).first()).toHaveAttribute('data-hidden', 'true', { timeout: 2000 })
      await expect(target.locator(`.evidence-region[data-item-id="${itemId}"]`)).toHaveAttribute('data-hidden', 'true', { timeout: 2000 })
      await expect.poll(() => hiddenInModel(target, itemId!), { timeout: 2000 }).toBe(true)
    }
    expect(performance.now() - start, 'The remote edit must arrive within two seconds').toBeLessThan(2000)
    await expect(a.box).toHaveCSS('opacity', '0.4')
    await expect(b.box.locator(':scope > rect')).toHaveCSS('stroke-dasharray', '5px, 4px')
    const undoResponse = page.waitForResponse((res) => res.request().method() === 'POST' && /\/api\/chats\/[^/]+\/messages$/.test(new URL(res.url()).pathname))
    await page.locator('.scene-command-undo').last().click()
    const response = await undoResponse
    expect(response.request().postDataJSON()).toEqual({ content: 'undo', doc_ids: [docId] })
    expect((await streamedAnswer(response)).answer.abstained).toBe(false)
    for (const target of [page, other]) {
      await expect(target.locator(`.scene-tag[data-item-id="${itemId}"]`).first()).toHaveAttribute('data-hidden', 'false', { timeout: 2000 })
      await expect(target.locator(`.evidence-region[data-item-id="${itemId}"]`)).toHaveAttribute('data-hidden', 'false', { timeout: 2000 })
      await expect.poll(() => hiddenInModel(target, itemId!), { timeout: 2000 }).toBe(false)
    }
  } finally { await context.close() }
})
