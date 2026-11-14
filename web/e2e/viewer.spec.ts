import { expect, test, type Locator, type Page } from '@playwright/test'
import type { Document } from '../src/lib/types'
import { viewerEvidence } from '../src/lib/viewer-evidence'
import { streamedAnswer } from './streamed-answer'

const fixtureId = 'cubicasa5k__colorful-11397'

test.setTimeout(60_000)

async function waitForDrawing(viewer: Locator) {
  const image = viewer.getByRole('img', { name: /Drawing:/ })
  await expect(image).toBeVisible({ timeout: 15_000 })
  await expect.poll(() => image.evaluate((node: HTMLImageElement) => node.complete && node.naturalWidth > 0), { timeout: 15_000 }).toBe(true)
  // Image decoding and ResizeObserver fitting finish independently. Wait for real dimensions
  // and a stable transform before interacting with zoom or checking projected evidence.
  let previous = ''
  await expect.poll(async () => {
    const current = await viewer.locator('.drawing-plane').evaluate((node) => {
      const bounds = node.getBoundingClientRect()
      return bounds.width > 0 && bounds.height > 0 ? getComputedStyle(node).transform : ''
    })
    const stable = !!current && current === previous
    previous = current
    return stable
  }, { timeout: 15_000, intervals: [100, 200, 300] }).toBe(true)
}

async function askFixture(page: Page) {
  const metadata = await page.request.get(`http://localhost:8000/api/docs/${fixtureId}`)
  expect(metadata.ok()).toBe(true)
  const fixture = await metadata.json() as Document
  await page.goto('/#/chat')
  await expect(page.getByText('Connected workspace', { exact: true })).toBeVisible()
  const composer = page.getByRole('combobox', { name: 'Ask about your drawings' })
  await composer.fill('@colorful-11397')
  const option = page.getByRole('option').filter({ hasText: fixture.title })
  await expect(option).toBeVisible()
  await option.click()
  await expect(page.getByLabel('Selected documents')).toContainText(fixture.title)
  await composer.fill('How many windows are there?')
  const response = page.waitForResponse((res) => res.request().method() === 'POST' && /\/api\/chats\/[^/]+\/messages$/.test(new URL(res.url()).pathname), { timeout: 30_000 })
  await page.getByRole('button', { name: 'Send question', exact: true }).click()
  const answer = await streamedAnswer(await response)
  expect(answer.answer.abstained).toBe(false)
  expect(answer.doc_ids).toContain(fixtureId)
  const chip = page.locator('.answer-text').getByRole('button', { name: 'Open citation 1', exact: true })
  await expect(chip).toBeVisible()
  await chip.click()
  const citation = answer.citations.find((source) => source.n === 1)
  expect(citation).toBeTruthy()
  return viewerEvidence(answer, citation!).regions
}

async function expectInside(box: Locator, viewport: Locator) {
  await expect.poll(async () => {
    const inner = await box.boundingBox(), outer = await viewport.boundingBox()
    const epsilon = .5 // CSS-to-device-pixel rounding at fractional fitted scales.
    return !!inner && !!outer && inner.width > 0 && inner.height > 0 && inner.x >= outer.x - epsilon && inner.y >= outer.y - epsilon &&
      inner.x + inner.width <= outer.x + outer.width + epsilon && inner.y + inner.height <= outer.y + outer.height + epsilon
  }, { timeout: 15_000 }).toBe(true)
}

test('citation opens its page beside chat with numbered evidence, navigation and permanent credit', async ({ page, request }) => {
  // Stable document tags must never replace an ordinary answer's numbers.
  await page.route(`**/api/docs/${fixtureId}/files/scene.json`, (route) => route.fulfill({ json: {
    items: Object.fromEntries(Array.from({ length: 50 }, (_, n) => [`window-${String(n + 1).padStart(3, '0')}`, { tag: `W${n + 1}` }])),
  } }))
  const response = await request.get(`http://localhost:8000/api/docs/${fixtureId}`)
  expect(response.ok()).toBe(true)
  const fixture = await response.json() as Document
  expect(fixture.credit).toBeTruthy()
  expect(fixture.licence).toBeTruthy()
  const imageRequests: string[] = []
  page.on('request', (req) => { if (req.url().includes(`/api/docs/${fixtureId}/pages/1/image`)) imageRequests.push(req.url()) })
  const regions = await askFixture(page)
  const viewer = page.getByRole('region', { name: 'Drawing viewer' })
  const viewport = viewer.getByTestId('drawing-viewport')
  await waitForDrawing(viewer)
  await expect(viewer.locator('.evidence-region').first()).toHaveAttribute('data-tag', /^W\d+$/)
  await expect(viewer.locator('.evidence-region > svg > text')).toHaveText(regions.map((region) => region.label))
  expect(imageRequests).toHaveLength(1)
  await expectInside(viewer.getByTestId('evidence-box-1'), viewport)
  expect(regions.length).toBeGreaterThan(1)
  await expect(viewer.getByTestId('source-position')).toHaveText(`1 of ${regions.length}`)
  const credit = viewer.getByTestId('drawing-credit')
  await expect(credit).toContainText(fixture.credit)
  await expect(credit).toContainText(fixture.licence)
  await expect(credit).toBeInViewport()
  await expect(page.getByRole('combobox', { name: 'Ask about your drawings' })).toBeVisible()

  await viewer.getByRole('button', { name: 'Next source', exact: true }).click()
  await expect(viewer.getByTestId('source-position')).toHaveText(`2 of ${regions.length}`)
  await expectInside(viewer.getByTestId('evidence-box-2'), viewport)
  await viewer.getByRole('button', { name: 'Zoom in', exact: true }).click()
  await expect(viewer.getByLabel('Zoom level', { exact: true })).toHaveText('125%')
  await viewer.getByRole('button', { name: 'Fit drawing', exact: true }).click()
  await expect(viewer.getByLabel('Zoom level', { exact: true })).toHaveText('100%')
  const splitter = page.getByRole('separator', { name: 'Resize chat and drawing' })
  await splitter.focus()
  await page.keyboard.press('ArrowLeft')
  await expect(splitter).toHaveAttribute('aria-valuenow', '46')
  await expect(credit).toBeInViewport()
  await viewer.getByRole('button', { name: 'Close drawing viewer' }).click()
  await expect(viewer).toHaveCount(0)
})

test('phone opens a full-screen sheet and returns focus to the citation when closed', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await askFixture(page)
  const viewer = page.getByRole('dialog', { name: 'Drawing viewer' })
  await expect(viewer).toHaveAttribute('aria-modal', 'true')
  await waitForDrawing(viewer)
  await expectInside(viewer.getByTestId('evidence-box-1'), viewer.getByTestId('drawing-viewport'))
  await expect(viewer.getByTestId('drawing-credit')).toBeInViewport()
  await expect(viewer.getByRole('button', { name: 'Close drawing viewer' })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(viewer).toHaveCount(0)
  await expect(page.locator('.answer-text').getByRole('button', { name: 'Open citation 1', exact: true })).toBeFocused()
})
