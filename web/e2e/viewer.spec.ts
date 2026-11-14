import { expect, test, type Locator, type Page } from '@playwright/test'
import type { Document } from '../src/lib/types'

const fixtureId = 'cubicasa5k__colorful-11397'

async function askFixture(page: Page) {
  await page.goto('/#/chat')
  await expect(page.getByText('Connected workspace', { exact: true })).toBeVisible()
  const composer = page.getByRole('combobox', { name: 'Ask about your drawings' })
  await composer.fill('@colorful-11397')
  await page.getByRole('option').filter({ hasText: 'colorful-11397' }).click()
  await composer.fill('How many windows are there?')
  await page.getByRole('button', { name: 'Send question', exact: true }).click()
  const chip = page.locator('.answer-text').getByRole('button', { name: 'Open citation 1', exact: true })
  await expect(chip).toBeVisible()
  await chip.click()
}

async function expectInside(box: Locator, viewport: Locator) {
  await expect.poll(async () => {
    const inner = await box.boundingBox(), outer = await viewport.boundingBox()
    return !!inner && !!outer && inner.x >= outer.x && inner.y >= outer.y &&
      inner.x + inner.width <= outer.x + outer.width && inner.y + inner.height <= outer.y + outer.height
  }).toBe(true)
}

test('citation opens its page beside chat with numbered evidence, navigation and permanent credit', async ({ page, request }) => {
  const response = await request.get(`http://localhost:8000/api/docs/${fixtureId}`)
  expect(response.ok()).toBe(true)
  const fixture = await response.json() as Document
  expect(fixture.credit).toBeTruthy()
  expect(fixture.licence).toBeTruthy()
  const imageRequests: string[] = []
  page.on('request', (req) => { if (req.url().includes(`/api/docs/${fixtureId}/pages/1/image`)) imageRequests.push(req.url()) })
  await askFixture(page)
  const viewer = page.getByRole('region', { name: 'Drawing viewer' })
  const viewport = viewer.getByTestId('drawing-viewport')
  const image = viewer.getByRole('img', { name: /Drawing:/ })
  await expect(image).toBeVisible()
  await expect.poll(() => image.evaluate((node: HTMLImageElement) => node.complete && node.naturalWidth > 0)).toBe(true)
  expect(imageRequests).toHaveLength(1)
  await expectInside(viewer.getByTestId('evidence-box-1'), viewport)
  await expect(viewer.getByTestId('source-position')).toHaveText('1 of 13')
  const credit = viewer.getByTestId('drawing-credit')
  await expect(credit).toContainText(fixture.credit)
  await expect(credit).toContainText(fixture.licence)
  await expect(credit).toBeInViewport()
  await expect(page.getByRole('combobox', { name: 'Ask about your drawings' })).toBeVisible()

  await viewer.getByRole('button', { name: 'Next source', exact: true }).click()
  await expect(viewer.getByTestId('source-position')).toHaveText('2 of 13')
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
  await expect(viewer.getByRole('img', { name: /Drawing:/ })).toBeVisible()
  await expectInside(viewer.getByTestId('evidence-box-1'), viewer.getByTestId('drawing-viewport'))
  await expect(viewer.getByTestId('drawing-credit')).toBeInViewport()
  await expect(viewer.getByRole('button', { name: 'Close drawing viewer' })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(viewer).toHaveCount(0)
  await expect(page.locator('.answer-text').getByRole('button', { name: 'Open citation 1', exact: true })).toBeFocused()
})
