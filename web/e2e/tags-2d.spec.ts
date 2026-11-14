import { expect, test } from '@playwright/test'
import { fileURLToPath } from 'node:url'

// 2D evidence tags: dense tags collapse (no overlap), the legend leads with the answer total.
const shots = fileURLToPath(new URL('../../results/qa/shots/', import.meta.url))
const docId = 'ifc_bench__ac20-arc'
test.setTimeout(120_000)

test('2D tags do not overlap and the legend shows totals', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/#/data')
  await page.getByRole('searchbox', { name: 'Search documents' }).fill('AC20')
  const row = page.locator(`[data-doc-id="${docId}"]`)
  await expect(row).toBeVisible({ timeout: 30_000 })
  await row.getByRole('button', { name: /^Open / }).click()
  await page.getByRole('complementary', { name: 'Document details' }).getByRole('button', { name: 'Ask about it', exact: true }).last().click()
  const composer = page.getByRole('combobox', { name: 'Ask about your drawings' })
  await expect(composer).toBeEnabled({ timeout: 20_000 })
  await composer.fill('how many doors and windows')
  await page.getByRole('button', { name: 'Send question', exact: true }).click()
  const card = page.getByTestId('answer-card').last()
  await expect(card.locator('.answer-text')).toBeVisible({ timeout: 60_000 })
  await card.getByRole('button', { name: /^Open citation 1$/ }).first().click()
  const viewer = page.getByRole('region', { name: 'Drawing viewer', exact: true })
  await expect(viewer.getByTestId(/^evidence-box-\d+$/).first()).toBeVisible({ timeout: 30_000 })
  await page.waitForTimeout(800)
  const shown = await viewer.locator('.evidence-region:not(.tag-collapsed):not(.is-leaving) > svg:not(.evidence-secondary-tag)').evaluateAll((nodes) =>
    nodes.map((n) => n.getBoundingClientRect()).map((r) => ({ x: r.x, y: r.y, w: r.width, h: r.height })))
  let overlaps = 0
  for (let i = 0; i < shown.length; i++) for (let j = i + 1; j < shown.length; j++) {
    const a = shown[i], b = shown[j]
    if (a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y) overlaps++
  }
  expect(overlaps, `${shown.length} visible tags`).toBe(0)
  const legend = viewer.getByTestId('kind-legend')
  await expect(legend).toContainText(/Doors \d+/)
  console.log(JSON.stringify({ visibleTags: shown.length, legend: await legend.innerText() }))
  await page.screenshot({ path: `${shots}tags2d-after.png` })
})
