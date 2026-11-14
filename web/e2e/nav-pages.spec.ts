import { expect, test } from '@playwright/test'
import type { ChangeEntry } from '../src/lib/types'

const api = 'http://localhost:8000'
test.setTimeout(90_000)

test('Compare shows a real version pair with numbered boxes and readings', async ({ page, request }) => {
  const { changes } = await (await request.get(`${api}/api/changes`)).json() as { changes: ChangeEntry[] }
  const smallest = changes.filter((entry) => entry.id.startsWith('ser:') && (entry.summary.n_changes ?? 0) > 0)
    .reduce((best, entry) => entry.summary.n_changes! < best.summary.n_changes! ? entry : best)
  await page.goto('/#/compare')
  const screen = page.getByRole('region', { name: 'Compare', exact: true })
  await expect(page.getByRole('heading', { name: 'Compare', level: 1, exact: true })).toBeVisible()
  await expect(screen.getByLabel('Drawing', { exact: true }).locator('option').first()).toBeAttached()
  await screen.getByLabel('Drawing', { exact: true }).selectOption(smallest.summary.series_id!)
  await screen.getByLabel('Versions', { exact: true }).selectOption(smallest.id)
  const detail = await (await request.get(`${api}/api/changes/${smallest.id}`)).json() as { changes: { n: number }[] }
  const readings = screen.getByRole('complementary', { name: 'Differences' })
  await expect(readings.locator('article')).toHaveCount(detail.changes.length)
  await expect(readings.locator('article').first().locator('.cmp-number')).toHaveText(String(detail.changes[0].n))
  await expect(screen.getByRole('img', { name: 'Older version' })).toBeVisible()
  await expect(screen.getByRole('img', { name: 'Newer version' })).toBeVisible()
  await expect(screen.locator('.cmp-box').first()).toBeVisible()
  await screen.getByRole('button', { name: 'Wipe', exact: true }).click()
  await expect(screen.getByRole('slider', { name: 'Wipe position' })).toHaveValue('50')
  await screen.getByRole('button', { name: 'Overlay', exact: true }).click()
  await expect(screen.getByRole('img', { name: 'Newer version' })).toHaveCSS('opacity', '0.5')
})

test('Library lists live skills and automations', async ({ page, request }) => {
  const body = await (await request.get(`${api}/api/skills`)).json() as { skills?: { name: string }[] } | { name: string }[]
  const list = Array.isArray(body) ? body : body.skills ?? []
  expect(list.length).toBeGreaterThan(0)
  await page.goto('/#/library')
  await expect(page.getByRole('heading', { name: 'Library', level: 1, exact: true })).toBeVisible()
  await expect(page.getByRole('tabpanel').getByText(list[0].name, { exact: true }).first()).toBeVisible()
  await page.getByRole('tab', { name: 'Automations' }).click()
  await expect(page.getByRole('tab', { name: 'Automations' })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('tabpanel')).not.toBeEmpty()
})

test('Tools shows the findings controls', async ({ page }) => {
  await page.goto('/#/tools')
  await expect(page.getByRole('heading', { name: 'Tools', level: 1, exact: true })).toBeVisible()
  const screen = page.getByRole('region', { name: 'Findings', exact: true })
  await expect(screen.getByLabel('Drawing', { exact: true })).toBeVisible()
  await expect(screen.getByRole('button', { name: 'Run checks', exact: true })).toBeVisible()
})

test('phone: Compare, Library and Tools are reachable from More without overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  const nav = page.getByRole('navigation', { name: 'Mobile navigation', exact: true })
  for (const label of ['Compare', 'Library', 'Tools']) {
    await nav.getByText('More', { exact: true }).click()
    await nav.getByRole('link', { name: label, exact: true }).click()
    await expect(page.getByRole('heading', { name: label, level: 1, exact: true })).toBeVisible()
    await page.waitForTimeout(500)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  }
})
