import { expect, test, type Locator, type Page } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import type { Answer } from '../src/lib/types'
import type { LinkedViewerCanvas } from '../src/viewer3d/Viewer3D'
import { KIND_COLORS } from '../src/lib/kind-colors'
import { streamedAnswer } from './streamed-answer'

// W-52: run with make dev (fake model provider), using the real API and AC20 artifacts.
// LEAD runs the browser via scripts/heavy.sh; workers only typecheck and --list this spec.
const docId = 'ifc_bench__ac20-arc'
const shots = fileURLToPath(new URL('../../results/qa/shots/', import.meta.url))
const drawingOf = (page: Page) => page.getByRole('region', { name: 'Drawing viewer', exact: true })
const cardOf = (page: Page, question: string) => page.getByTestId('answer-card')
  .filter({ has: page.getByText(question, { exact: true }) }).last()
const boxesOf = (drawing: Locator) => drawing.getByTestId(/^evidence-box-\d+$/)
const rgb = (hex: string) => {
  const value = Number.parseInt(hex.slice(1), 16)
  return `rgb(${value >> 16}, ${(value >> 8) & 255}, ${value & 255})`
}

test.use({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' })
test.setTimeout(240_000)

async function ask(page: Page, question: string, chatId?: string) {
  const composer = page.getByRole('combobox', { name: 'Ask about your drawings' })
  await expect(composer).toBeEnabled()
  await composer.fill(question)
  const pending = page.waitForResponse((response) => response.request().method() === 'POST'
    && /\/api\/chats\/[^/]+\/messages$/.test(new URL(response.url()).pathname))
  await page.getByRole('button', { name: 'Send question', exact: true }).click()
  const response = await pending
  const id = new URL(response.url()).pathname.split('/')[3]
  if (chatId) expect(id, 'Every question stays in the original chat').toBe(chatId)
  expect(response.request().postDataJSON()).toEqual({ content: question, doc_ids: [docId] })
  const answer = await streamedAnswer(response)
  expect(answer.answer.abstained).toBe(false)
  expect(answer.trace.some((step) => step.stub), 'No generated/demo answers').toBe(false)
  expect(answer.cost.calls, 'Walk-through questions are answered by code').toEqual([])
  expect(answer.doc_ids).toContain(docId)
  const card = cardOf(page, question)
  await expect(card.getByTestId('answer-cost')).toBeVisible()
  return { answer, card, chatId: id }
}

async function expectCounts(card: Locator, answer: Answer) {
  const counts = answer.answer.value
  expect(counts).toEqual(expect.objectContaining({ door: expect.any(Number), window: expect.any(Number) }))
  const values = counts as Record<'door' | 'window', number>
  for (const kind of ['door', 'window'] as const) {
    expect(values[kind]).toBeGreaterThan(0)
    await expect(card.locator('.answer-text')).toContainText(new RegExp(`\\b${values[kind]}\\s+${kind}s?\\b`, 'i'))
    expect(answer.evidence.boxes.filter((box) => box.kind === kind)).toHaveLength(values[kind])
  }
  expect(answer.evidence.boxes.map((box) => box.label))
    .toEqual(answer.evidence.boxes.map((_, index) => String(index + 1)))
  return values
}

async function expectDrawing(drawing: Locator, answer: Answer) {
  await expect(drawing.getByTestId('drawing-viewport')).toBeVisible()
  const image = drawing.getByRole('img', { name: /^Drawing:/ })
  await expect.poll(() => image.evaluate((node: HTMLImageElement) => node.complete && node.naturalWidth > 0)).toBe(true)
  const expected = answer.evidence.boxes.filter((box) => box.page === answer.citations[0].page)
  expect(expected.length).toBeGreaterThan(0)
  await expect(boxesOf(drawing)).toHaveCount(expected.length)
  await expect.poll(() => boxesOf(drawing).evaluateAll((nodes) => nodes.map((node) => node.getAttribute('data-item-id')).sort()))
    .toEqual(expected.map((box) => box.item_id).sort())
  for (const box of expected) {
    await expect(drawing.getByTestId(`evidence-box-${box.label}`)).toHaveAttribute('data-item-id', box.item_id)
  }
}

async function modelHidden(page: Page) {
  return drawingOf(page).locator('canvas[aria-label="3D building model"]').evaluate((canvas: LinkedViewerCanvas) => {
    if (!canvas.__viewer3d) throw new Error('The 3D command-state handle is not ready')
    return [...canvas.__viewer3d.commandState().hidden].sort()
  })
}

// Assert the destination of every visible answer button; unknown/new actions fail explicitly.
async function exerciseButtons(page: Page, card: Locator) {
  const thought = card.locator('.thought-process')
  await thought.locator('summary').click()
  await expect(thought).toHaveAttribute('open', '')
  await expect(thought.locator('p').first()).toBeVisible()
  await thought.locator('summary').click()
  const sources = card.locator('.sources-detail')
  if (await sources.count()) {
    await sources.locator('summary').click()
    await expect(sources).toHaveAttribute('open', '')
    await expect(sources.getByRole('button').first()).toBeVisible()
  }
  // Expose the capped citations/tags too, then exercise their actual destinations.
  const expanders = card.locator('.citation-more, .scene-tags-more')
  for (const expander of await expanders.all()) {
    if (await expander.getAttribute('aria-expanded') === 'false') {
      await expander.click()
      await expect(expander).toHaveAttribute('aria-expanded', 'true')
    }
  }
  const occurrences = new Map<string, number>()
  const actions: { name: string; occurrence: number }[] = []
  for (const button of await card.getByRole('button').all()) {
    if (!await button.isVisible() || await button.getAttribute('aria-expanded') !== null) continue
    const name = (await button.getAttribute('aria-label') ?? await button.innerText()).trim()
    const occurrence = occurrences.get(name) ?? 0
    occurrences.set(name, occurrence + 1)
    actions.push({ name, occurrence })
  }
  expect(actions.length).toBeGreaterThan(0)
  for (const { name, occurrence } of actions) {
    await test.step(`Answer action: ${name} (${occurrence + 1})`, async () => {
      const button = card.getByRole('button', { name, exact: true }).nth(occurrence)
      await expect(button).toBeEnabled()
      if (/^Open (citation|document|source document) /.test(name) || /^Show .+ on drawing/.test(name)) {
        await button.click()
        const drawing = drawingOf(page)
        await expect(drawing).toBeVisible()
        await expect(drawing.getByRole('button', { name: '2D', exact: true })).toHaveAttribute('aria-pressed', 'true')
        if (/^Open citation /.test(name)) await expect(button).toHaveAttribute('aria-pressed', 'true')
        if (/^Show .+ on drawing/.test(name)) {
          const item = await button.getAttribute('data-item-id')
          await expect(drawing.locator(`[data-item-id="${item}"]`).first()).toBeVisible()
        } else await expect(boxesOf(drawing).first()).toBeVisible()
      } else if (name === 'Visualise it') {
        await button.click()
        await expect(drawingOf(page).getByRole('region', { name: '3D viewer', exact: true }))
          .toHaveAttribute('data-state', 'ready', { timeout: 60_000 })
        await expect(drawingOf(page).getByTestId('build-slider')).toBeVisible()
        await drawingOf(page).getByRole('button', { name: '2D', exact: true }).click()
      } else if (name === 'Export report') {
        await button.click()
        const dialog = page.getByRole('dialog', { name: 'Export site report' })
        await expect(dialog).toBeVisible()
        await expect(dialog.getByRole('button', { name: 'Copy as Markdown' })).toBeEnabled({ timeout: 30_000 })
        await dialog.getByRole('button', { name: 'Close export report', exact: true }).click()
        await expect(dialog).toHaveCount(0)
        await expect(button).toBeFocused()
      } else if (name === 'Play spoken answer') {
        const speech = page.waitForRequest((request) => new URL(request.url()).pathname === '/api/tts' && request.method() === 'POST')
        await button.click()
        expect((await speech).postDataJSON().text).toBeTruthy()
        const voice = card.locator('.voice-control')
        await expect.poll(async () => await voice.getByRole('button').getAttribute('aria-pressed') === 'true'
          || Boolean((await voice.getByRole('status').textContent())?.trim())).toBe(true)
        const stop = voice.getByRole('button', { name: 'Stop', exact: true })
        if (await stop.count()) await stop.click()
        await expect(voice.getByRole('button', { name: 'Play spoken answer', exact: true })).toHaveAttribute('aria-pressed', 'false')
      } else if (name === 'Undo') {
        const pending = page.waitForResponse((response) => response.request().method() === 'POST'
          && /\/api\/chats\/[^/]+\/messages$/.test(new URL(response.url()).pathname))
        await button.click()
        const response = await pending
        expect(response.request().postDataJSON().content).toBe('undo')
        const answer = await streamedAnswer(response)
        expect(answer.answer.abstained).toBe(false)
        expect(answer.evidence.scene.commands?.length).toBeGreaterThan(0)
        await expect(cardOf(page, answer.question).getByTestId('answer-cost')).toBeVisible()
      } else throw new Error(`Answer button has no verified destination: ${name}`)
    })
  }
  for (const expander of await expanders.all()) {
    await expander.click()
    await expect(expander).toHaveAttribute('aria-expanded', 'false')
  }
}

test('fire-safety walk-through before a renovation meeting: AC20, one chat, real local API', async ({ page, request }) => {
  await mkdir(shots, { recursive: true })
  const shot = (step: string) => page.screenshot({ path: `${shots}w52-${step}.png`, fullPage: true })
  let chatId!: string
  let ground!: Awaited<ReturnType<typeof ask>>
  let first!: Awaited<ReturnType<typeof ask>>
  let toilets!: Awaited<ReturnType<typeof ask>>
  let removed!: Awaited<ReturnType<typeof ask>>
  let reset!: Awaited<ReturnType<typeof ask>>

  await test.step('1. Data → search AC20 → open → Ask', async () => {
    // Enables only the existing read-only 3D state handle; the UI/API remain real.
    await page.goto('/?viewer3dTest=1#/data')
    await expect(page.getByText('Connected workspace', { exact: true })).toBeVisible()
    await page.getByRole('searchbox', { name: 'Search documents' }).fill('AC20')
    const row = page.locator(`[data-doc-id="${docId}"]`)
    await expect(row).toBeVisible()
    await row.getByRole('button', { name: /^Open / }).click()
    const detail = page.getByRole('complementary', { name: 'Document details' })
    await expect(detail).toBeVisible()
    await detail.getByRole('button', { name: 'Ask about it', exact: true }).last().click()
    await expect(page.getByLabel('Selected documents')).toContainText(/AC20/i)
    await shot('01-data-ask')
  })

  await test.step('2. Ground floor counts include doors, windows and numbered evidence', async () => {
    ground = await ask(page, 'How many doors and windows are on the ground floor?')
    chatId = ground.chatId
    await expectCounts(ground.card, ground.answer)
    await expect(ground.card.getByRole('button', { name: 'Open citation 1', exact: true }).first()).toBeVisible()
    await shot('02-ground-counts')
  })

  await test.step('3. Citation 1 opens boxes and the two-colour kind legend', async () => {
    await ground.card.getByRole('button', { name: 'Open citation 1', exact: true }).first().click()
    const drawing = drawingOf(page)
    await expectDrawing(drawing, ground.answer)
    const legend = drawing.getByTestId('kind-legend').filter({ visible: true })
    await expect(legend.locator('li')).toHaveCount(2)
    for (const kind of ['door', 'window'] as const) {
      const count = ground.answer.evidence.boxes.filter((box) => box.kind === kind).length
      await expect(legend.locator(`[data-kind="${kind}"]`)).toHaveText(`${KIND_COLORS[kind].plural} ${count}`)
      await expect(legend.locator(`[data-kind="${kind}"] .kind-legend-swatch`)).toHaveCSS('background-color', rgb(KIND_COLORS[kind].color))
      await expect(boxesOf(drawing).and(drawing.locator(`[data-kind="${kind}"]`)).locator('> rect').first())
        .toHaveCSS('stroke', rgb(KIND_COLORS[kind].color))
    }
    expect(KIND_COLORS.door.color).not.toBe(KIND_COLORS.window.color)
    await shot('03-citation-legend')
  })

  await test.step('4. First floor follow-up updates counts and boxes without reloading the image', async () => {
    const drawing = drawingOf(page)
    const image = await drawing.getByRole('img', { name: /^Drawing:/ }).elementHandle()
    expect(image).not.toBeNull()
    const src = await image!.getAttribute('src')
    const images: string[] = []
    const recordImage = (request: import('@playwright/test').Request) => {
      if (/\/pages\/\d+\/image$/.test(new URL(request.url()).pathname)) images.push(request.url())
    }
    page.on('request', recordImage)
    try {
      first = await ask(page, 'And on the first floor?', chatId)
      const firstCounts = await expectCounts(first.card, first.answer)
      expect(firstCounts).not.toEqual(ground.answer.answer.value)
      await expectDrawing(drawing, first.answer)
      expect(await image!.evaluate((original) => original === document.querySelector('[data-testid="drawing-viewport"] img'))).toBe(true)
      // The first-floor answer cites the first-floor sheet: the same <img> node swaps to it in place (one page fetch, no reload).
      const shownPage = Number((await drawing.getByRole('img', { name: /^Drawing:/ }).getAttribute('alt'))?.match(/page (\d+)$/)?.[1])
      const citedPage = first.answer.citations[0].page
      expect(shownPage).toBe(citedPage)
      if (citedPage === ground.answer.citations[0].page) { expect(await image!.getAttribute('src')).toBe(src); expect(images, 'Same page, no new fetch').toEqual([]) }
      else expect(images.length, 'one fetch for the new sheet').toBeLessThanOrEqual(1)
    } finally { page.off('request', recordImage); await image!.dispose() }
    await shot('04-first-floor-in-place')
  })

  await test.step('5. Locate toilets with boxes', async () => {
    toilets = await ask(page, 'Where are the toilets?', chatId)
    expect(toilets.answer.evidence.boxes.some((box) => box.kind === 'toilet')).toBe(true)
    await expectDrawing(drawingOf(page), toilets.answer)
    await shot('05-toilets')
  })

  await test.step('6. Visualise it loads 3D and the build-up slider steps both ways', async () => {
    await toilets.card.getByRole('button', { name: 'Visualise it', exact: true }).click()
    const drawing = drawingOf(page)
    await expect(drawing.getByRole('region', { name: '3D viewer', exact: true }))
      .toHaveAttribute('data-state', 'ready', { timeout: 60_000 })
    const slider = drawing.getByTestId('build-slider')
    await expect(slider).toBeVisible()
    expect(Number(await slider.getAttribute('data-total'))).toBeGreaterThan(1)
    await slider.getByRole('slider', { name: 'Build step', exact: true }).fill('1')
    await expect(slider).toHaveAttribute('data-step', '1')
    await slider.getByRole('button', { name: 'Next step', exact: true }).click()
    await expect(slider).toHaveAttribute('data-step', '2')
    await expect(slider.getByTestId('build-step-label')).toContainText('Step 2 of ')
    await slider.getByRole('button', { name: 'Previous step', exact: true }).click()
    await expect(slider).toHaveAttribute('data-step', '1')
    await slider.getByRole('slider', { name: 'Build step', exact: true }).fill((await slider.getAttribute('data-total'))!)
    await shot('06-3d-build-up')
  })

  await test.step('7. Remove the front door and check the sourced §33 advisor card', async () => {
    removed = await ask(page, 'Remove the front door. Is it still compliant?', chatId)
    const command = removed.answer.evidence.scene.commands?.find((entry) => entry.op === 'hide')
    expect(command?.item_ids).toHaveLength(1)
    await expect(removed.card.getByTestId('answer-advisor-cards')).toBeVisible()
    await expect(removed.card.getByTestId('answer-advisor-cards')).toContainText('33')
    const advice = removed.card.getByTestId('answer-advisor-cards')
    for (const source of await advice.locator('details').all()) {
      await source.locator('summary').click()
      await expect(source.locator('blockquote')).toBeVisible()
      await expect(source.locator('blockquote')).not.toBeEmpty()
    }
    await expect.poll(() => modelHidden(page)).toEqual([...command!.item_ids].sort())
    await shot('07-front-door-advice')
  })

  await test.step('8. Reset restores the model and clears both hidden lists', async () => {
    reset = await ask(page, 'Reset the model', chatId)
    expect(reset.answer.evidence.scene.commands).toContainEqual(expect.objectContaining({ op: 'reset' }))
    await expect.poll(() => modelHidden(page)).toEqual([])
    const response = await request.get(`/api/chats/${chatId}/scene-state?doc_id=${docId}`)
    expect(response.ok()).toBe(true)
    const saved = await response.json() as { states: { doc_id: string; hidden: string[] }[] }
    expect(saved.states.find((state) => state.doc_id === docId)?.hidden).toEqual([])
    await expect(removed.card.locator('[data-hidden="true"]')).toHaveCount(0)
    await shot('08-reset')
  })

  await test.step('9. Every visible answer button and source disclosure has a destination', async () => {
    for (const result of [ground, first, toilets, removed, reset]) await exerciseButtons(page, result.card)
    await shot('09-answer-actions')
  })
})
