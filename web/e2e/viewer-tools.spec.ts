import { readFile } from 'node:fs/promises'
import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test'
import type { Answer, Document } from '../src/lib/types'

const api = 'http://localhost:8000/api'
const drawingId = 'cubicasa5k__colorful-11397'
const notesId = 'opening_design__sports-complex-sheets-current-set-a-801-door-and-finish-schedules-wall-types'
test.setTimeout(60_000)

async function liveChat(request: APIRequestContext, docId: string, question: string) {
  const created = await request.post(`${api}/chats`, { data: { doc_ids: [docId], title: `WEB2: ${question}` } })
  expect(created.ok()).toBe(true)
  const { id } = await created.json() as { id: string }
  const response = await request.post(`${api}/chats/${id}/messages`, { data: { doc_ids: [docId], content: question }, timeout: 45_000 })
  expect(response.ok()).toBe(true)
  const stream = await response.text()
  expect(stream).not.toMatch(/"stub"\s*:\s*true/)
  const block = stream.replace(/\r\n/g, '\n').split('\n\n').find((event) => event.startsWith('event: answer\n'))
  expect(block, 'The real API must return an answer event').toBeTruthy()
  const answer = JSON.parse(block!.split('\n').filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trim()).join('\n')) as Answer
  expect(answer.answer.abstained).toBe(false)
  expect(answer.citations.length).toBeGreaterThan(0)
  return { id, answer }
}

async function openChat(page: Page, id: string, citation = 1, phone = false) {
  await page.goto(`/#/chat?chat=${encodeURIComponent(id)}`)
  const trigger = page.getByRole('button', { name: `Open citation ${citation}`, exact: true }).last()
  await expect(trigger).toBeVisible()
  await trigger.click()
  const viewer = page.getByRole(phone ? 'dialog' : 'region', { name: 'Drawing viewer', exact: true })
  await expect(viewer).toBeVisible()
  await ready(viewer)
  return viewer
}

async function ready(viewer: Locator) {
  const image = viewer.getByRole('img', { name: /Drawing:/ })
  await expect(image).toBeVisible()
  await expect.poll(() => image.evaluate((node: HTMLImageElement) => node.complete && node.naturalWidth > 0)).toBe(true)
  let previous = ''
  await expect.poll(async () => {
    const transform = await viewer.locator('.drawing-plane').evaluate((node) => getComputedStyle(node).transform)
    const stable = transform !== 'none' && transform === previous
    previous = transform; return stable
  }).toBe(true)
}

async function annotate(page: Page, viewer: Locator, tool: 'Highlight marker' | 'Pen annotations') {
  await viewer.getByRole('button', { name: tool, exact: true }).click()
  await expect(viewer.getByRole('button', { name: tool, exact: true })).toHaveAttribute('aria-pressed', 'true')
  const canvas = viewer.getByTestId('drawing-viewport')
  await canvas.focus()
  await canvas.press('0')
  await ready(viewer)
  const pageBox = await viewer.locator('.drawing-plane').boundingBox()
  expect(pageBox).toBeTruthy()
  const x = pageBox!.x + pageBox!.width * .25, y = pageBox!.y + pageBox!.height * .3
  await page.mouse.move(x, y)
  await page.mouse.down()
  await page.mouse.move(x + pageBox!.width * .25, y + pageBox!.height * .08, { steps: 10 })
  await page.mouse.up()
}

let drawingChat: { id: string; answer: Answer }
test.beforeAll(async ({ request }) => {
  drawingChat = await liveChat(request, drawingId, 'How many windows are there?')
})

test('search uses actual sheet labels, numbers yellow hits, navigates and reports no matches', async ({ page, request }) => {
  const response = await request.get(`${api}/docs/${drawingId}/planmap/1`)
  expect(response.ok()).toBe(true)
  const plan = await response.json() as { items: { label: string | null }[] }
  const expected = plan.items.filter((item) => item.label?.toLowerCase().includes('mh')).length
  expect(expected).toBeGreaterThan(1)
  const viewer = await openChat(page, drawingChat.id)
  await viewer.getByRole('button', { name: 'Search sheet', exact: true }).click()
  await viewer.getByRole('searchbox', { name: 'Find on sheet' }).fill('mh')
  const search = viewer.getByRole('search', { name: 'Find text on sheet' })
  await expect(search.getByRole('status')).toHaveText(`1 of ${expected} matches`)
  const hits = viewer.getByTestId('sheet-search-hit')
  await expect(hits).toHaveCount(expected)
  await expect(hits.locator('svg text')).toHaveText(Array.from({ length: expected }, (_, i) => String(i + 1)))
  expect(await hits.first().locator(':scope > rect').evaluate((node) => getComputedStyle(node).fill)).toBe('rgb(253, 224, 71)')
  await search.getByRole('button', { name: 'Next match', exact: true }).click()
  await expect(search.getByRole('status')).toHaveText(`2 of ${expected} matches`)
  await expect(hits.nth(1)).toHaveClass(/is-current/)
  await search.getByRole('button', { name: 'Previous match', exact: true }).click()
  await expect(search.getByRole('status')).toHaveText(`1 of ${expected} matches`)
  await viewer.getByRole('searchbox', { name: 'Find on sheet' }).fill('no-such-sheet-label-xyz')
  await expect(search.getByRole('status')).toHaveText('No matches')
  await expect(hits).toHaveCount(0)
  await page.keyboard.press('Escape')
  await expect(search).toHaveCount(0)
  await expect(viewer).toBeVisible()
})

test('marker and pen stay aligned through zoom and persist on reload, with undo and clear', async ({ page }) => {
  let viewer = await openChat(page, drawingChat.id)
  await annotate(page, viewer, 'Highlight marker')
  await expect(viewer.locator('[data-annotation="marker"]')).toHaveCount(1)
  await annotate(page, viewer, 'Pen annotations')
  const pen = viewer.locator('[data-annotation="pen"]')
  await expect(pen).toHaveCount(1)
  const points = await pen.getAttribute('points')
  await viewer.getByRole('button', { name: 'Done', exact: true }).click()
  await viewer.getByRole('button', { name: 'Fit drawing', exact: true }).click()
  await expect(viewer.getByLabel('Zoom level', { exact: true })).toHaveText('100%')
  await viewer.getByRole('button', { name: 'Zoom in', exact: true }).click()
  await expect(viewer.getByLabel('Zoom level', { exact: true })).toHaveText('125%')
  await expect(pen).toHaveAttribute('points', points!)
  const saved = await page.evaluate((id) => JSON.parse(localStorage.getItem(`hologram:annotations:${id}`) ?? '[]') as unknown[], drawingId)
  expect(saved).toHaveLength(2)
  await page.reload()
  viewer = await openChat(page, drawingChat.id)
  await expect(viewer.locator('[data-annotation="pen"]')).toHaveAttribute('points', points!)
  await expect(viewer.locator('[data-annotation="marker"]')).toHaveCount(1)
  await viewer.getByRole('button', { name: 'Undo annotation', exact: true }).click()
  await expect(viewer.locator('[data-annotation="pen"]')).toHaveCount(0)
  await expect(viewer.locator('[data-annotation="marker"]')).toHaveCount(1)
  await viewer.getByRole('button', { name: 'Clear page annotations', exact: true }).click()
  await expect(viewer.locator('[data-annotation]')).toHaveCount(0)
  expect(await page.evaluate((id) => localStorage.getItem(`hologram:annotations:${id}`), drawingId)).toBe('[]')
})

test('download returns the original file bytes from the source endpoint', async ({ page, request }) => {
  const original = await request.get(`${api}/docs/${drawingId}/source`)
  expect(original.ok()).toBe(true)
  const metadata = await request.get(`${api}/docs/${drawingId}`)
  const doc = await metadata.json() as Document
  const viewer = await openChat(page, drawingChat.id)
  const downloadEvent = page.waitForEvent('download')
  await viewer.getByRole('button', { name: 'Download original source', exact: true }).click()
  const download = await downloadEvent
  expect(download.suggestedFilename()).toMatch(new RegExp(`\\.(${doc.formats.join('|')})$`, 'i'))
  expect(await readFile((await download.path())!)).toEqual(await original.body())
})

test('real quoted note opens a side panel highlighted in yellow', async ({ page, request }) => {
  // Reuse an actual persisted reader answer when available so reruns need no model call.
  const listed = await request.get(`${api}/chats`)
  expect(listed.ok()).toBe(true)
  const candidates = ((await listed.json()) as { chats: { id: string; doc_id: string | null }[] }).chats.filter((chat) => chat.doc_id === notesId).slice(0, 5)
  let chat: { id: string; answer: Answer } | undefined
  for (const candidate of candidates) {
    const saved = await request.get(`${api}/chats/${candidate.id}`)
    expect(saved.ok()).toBe(true)
    const messages = ((await saved.json()) as { messages: { answer: Answer | null }[] }).messages
    const answer = messages.map((message) => message.answer).find((answer) => answer && !answer.answer.abstained && answer.citations.some((entry) => entry.kind === 'text' && entry.quote))
    if (answer) { chat = { id: candidate.id, answer }; break }
  }
  chat ??= await liveChat(request, notesId, 'What is the title of sheet A-801? Quote the printed title.')
  const citation = chat.answer.citations.find((entry) => entry.kind === 'text' && entry.quote)
  expect(citation, 'The drawing reader must supply a real quoted text citation').toBeTruthy()
  const viewer = await openChat(page, chat.id, citation!.n)
  const passage = viewer.getByRole('complementary', { name: 'Cited passage', exact: true })
  await expect(passage).toBeVisible()
  await expect(passage.getByTestId('cited-passage')).toHaveText(citation!.quote!)
  // Stoa parity: the passage highlight fades in after a .45s delay over .4s.
  await expect.poll(() => passage.getByTestId('cited-passage').evaluate((node) => getComputedStyle(node).backgroundColor), { timeout: 3000 }).toBe('rgb(254, 240, 138)')
  await passage.getByRole('button', { name: 'Close cited passage', exact: true }).click()
  await expect(passage).toHaveCount(0)
  await viewer.getByRole('button', { name: 'Show cited passage', exact: true }).click()
  await expect(passage).toBeVisible()
})

test('phone toolbar search and annotations remain usable', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const viewer = await openChat(page, drawingChat.id, 1, true)
  await expect(viewer.getByRole('button', { name: 'Download original source', exact: true })).toBeInViewport()
  await viewer.getByRole('button', { name: 'Search sheet', exact: true }).click()
  await viewer.getByRole('searchbox', { name: 'Find on sheet' }).fill('terassi')
  await expect(viewer.getByTestId('sheet-search-hit')).toHaveCount(2)
  await viewer.getByRole('button', { name: 'Close sheet search', exact: true }).click()
  await annotate(page, viewer, 'Pen annotations')
  await expect(viewer.locator('[data-annotation="pen"]')).toHaveCount(1)
  await expect(viewer.getByTestId('drawing-credit')).toBeInViewport()
  await viewer.getByRole('button', { name: 'Close drawing viewer', exact: true }).click()
  await expect(viewer).toHaveCount(0)
})
