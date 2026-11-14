import { expect, test, type Page } from '@playwright/test'
import type { Viewer } from '../src/viewer3d/viewer'
import type { LinkedViewerCanvas } from '../src/viewer3d/Viewer3D'
import { KIND_COLORS } from '../src/lib/kind-colors'

test.setTimeout(120_000)
test.use({ reducedMotion: 'reduce' })
const docId = 'ifc_bench__ac20-arc'
const doorId = '3qloCPnZDEQBom1ZjBlwJP'
type TestWindow = Window & typeof globalThis & { __viewer3d: Viewer }

// Cards below are generated for demo: only the advisor response is stubbed in the 3D test; scene and request are real.
const source = (n: number) => ({ type: 'document', ref: `fixture-${n}`, title: `Fixture source ${n} — generated for demo`, quote: 'Generated for demo.' })
const fixture = (ids: string[]) => ({ cards: [
  { card_id: 'fx-violation', kind: 'warning', severity: 'violation', title: 'Violation card — generated for demo', body: 'Body.', item_ids: ids, checked: ['R-848-33', 'R-1007-12'], source: source(1) },
  { card_id: 'fx-suggestion', kind: 'option', severity: 'suggestion', title: 'Suggestion card — generated for demo', body: 'Body.', item_ids: ids, source: source(2) },
  { card_id: 'fx-info', kind: 'info', severity: 'info', title: 'Info card — generated for demo', body: 'Body.', item_ids: ids, source: source(3) },
] })

async function openEdit(page: Page) {
  await page.goto(`/?doc=${docId}&viewer3dTest=1#/viewer-test`)
  const viewer = page.getByRole('region', { name: '3D viewer', exact: true })
  await expect(viewer).toHaveAttribute('data-state', 'ready', { timeout: 90_000 })
  await expect.poll(() => page.evaluate(() => (window as TestWindow).__viewer3d?.scene?.manifest.doc_id)).toBe(docId)
  await viewer.getByRole('button', { name: 'Edit', exact: true }).click()
  await page.getByLabel('3D building model', { exact: true }).evaluate((canvas, id) => (canvas as LinkedViewerCanvas).__viewer3d!.pick(id), doorId)
  return viewer
}
const bg = (page: Page, severity: string) => page.locator(`[data-advisor-card][data-severity="${severity}"]`).first().evaluate((el) => getComputedStyle(el).backgroundColor)

test('3D edit panel: hide posts op hide with item_ids; cards show severity colour and a Checked line', async ({ page }) => {
  await page.route('**/api/advise', (route) => route.fulfill({ json: fixture([doorId]) }), { times: 1 })
  const viewer = await openEdit(page)
  const request = page.waitForRequest((r) => r.url().endsWith('/api/advise') && r.method() === 'POST')
  await viewer.getByRole('button', { name: 'Remove', exact: true }).click()
  expect((await request).postDataJSON()).toMatchObject({ doc_id: docId, edit: { op: 'hide', item_ids: [doorId] } })
  await expect(viewer.locator('[data-advisor-card]')).toHaveCount(3)
  for (const severity of ['violation', 'suggestion', 'info']) await expect(viewer.locator(`[data-severity="${severity}"]`)).toHaveCount(1)
  const [red, amber, grey] = await Promise.all(['violation', 'suggestion', 'info'].map((s) => bg(page, s)))
  expect(new Set([red, amber, grey]).size).toBe(3)
  await expect(viewer.locator('[data-severity="violation"] .viewer3d-advisor-select')).toContainText('Violation')
  await expect(viewer.locator('[data-severity="violation"]').getByTestId('advisor-checked')).toHaveText('Checked: R-848-33, R-1007-12')
  await expect(viewer.locator('[data-severity="info"]').getByTestId('advisor-checked')).toHaveCount(0)
})

test('3D edit panel against the real advisor: every card carries a severity', async ({ page }) => {
  const viewer = await openEdit(page)
  await viewer.getByRole('button', { name: 'Remove', exact: true }).click()
  await expect(viewer.getByRole('status').filter({ hasText: 'Checking this change' })).toHaveCount(0, { timeout: 60_000 })
  const cards = viewer.locator('[data-advisor-card]')
  for (let i = 0; i < await cards.count(); i++) await expect(cards.nth(i)).toHaveAttribute('data-severity', /^(violation|suggestion|info)$/)
})

test('multi-kind answer: 2D legend and box colours per kind', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/#/chat')
  const composer = page.getByRole('combobox', { name: 'Ask about your drawings' })
  await composer.fill('@colorful-11397')
  await page.getByRole('option').filter({ hasText: 'colorful-11397' }).click()
  await composer.fill('How many windows and doors are there?')
  await page.getByRole('button', { name: 'Send question', exact: true }).click()
  await page.getByRole('button', { name: 'Open citation 1', exact: true }).first().click({ timeout: 90_000 })
  const drawing = page.getByRole('region', { name: 'Drawing viewer', exact: true })
  const legend = drawing.getByTestId('kind-legend')
  await expect(legend.locator('[data-kind="window"]')).toBeVisible()
  await expect(legend.locator('[data-kind="door"]')).toBeVisible()
  await expect(drawing.locator('.evidence-region[data-kind="window"] > rect').first()).toHaveCSS('stroke', /rgb\(0, 114, 178\)/)
  await expect(drawing.locator('.evidence-region[data-kind="door"] > rect').first()).toHaveCSS('stroke', /rgb\(213, 94, 0\)/)
  expect(KIND_COLORS.window.color).toBe('#0072B2')
})

test('answer card Visualise it opens the viewer in 3D', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/#/chat')
  const composer = page.getByRole('combobox', { name: 'Ask about your drawings' })
  await composer.fill('@colorful-11397')
  await page.getByRole('option').filter({ hasText: 'colorful-11397' }).click()
  await composer.fill('How many windows are there?')
  await page.getByRole('button', { name: 'Send question', exact: true }).click()
  await page.getByRole('button', { name: 'Visualise it', exact: true }).click({ timeout: 90_000 })
  await expect(page.getByRole('group', { name: 'Viewer mode' }).getByRole('button', { name: '3D', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('region', { name: '3D model pane' })).toBeVisible()
})

test('chat: hiding the front door shows advisor cards with severity and Checked on the answer', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/#/chat')
  const composer = page.getByRole('combobox', { name: 'Ask about your drawings' })
  await composer.fill('@ac20')
  await page.getByRole('option').filter({ hasText: /ac20/i }).first().click()
  await composer.fill('Remove the front door')
  await page.getByRole('button', { name: 'Send question', exact: true }).click()
  const cards = page.getByTestId('answer-advisor-cards')
  await expect(cards).toBeVisible({ timeout: 90_000 })
  const first = cards.locator('[data-advisor-card]').first()
  await expect(first).toHaveAttribute('data-severity', /^(violation|suggestion|info)$/)
  await expect(cards.locator('[data-severity="violation"]').first()).toBeVisible()
  await expect(cards.getByTestId('advisor-checked').first()).toContainText('Checked:')
})
