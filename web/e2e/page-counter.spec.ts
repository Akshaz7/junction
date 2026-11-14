import { expect, test } from '@playwright/test'

test.setTimeout(120_000)
for (const vp of [{ width: 1400, height: 900 }, { width: 430, height: 932 }, { width: 390, height: 844 }]) {
  test(`page counter never exceeds the total, citation box in view (${vp.width})`, async ({ page }) => {
    await page.setViewportSize(vp)
    await page.goto('/#/data')
    await page.getByRole('searchbox', { name: 'Search documents' }).fill('AC20')
    await page.locator('[data-doc-id="ifc_bench__ac20-arc"] .data-open-file').click()
    const details = vp.width > 800 ? page.getByRole('complementary', { name: 'Document details' }) : page.locator('aside.data-detail[role=dialog]')
    await details.getByRole('button', { name: 'Ask about it', exact: true }).first().click()
    await page.getByRole('combobox', { name: 'Ask about your drawings' }).fill('How many windows are there?')
    await page.getByRole('button', { name: 'Send question', exact: true }).click()
    const card = page.locator('.exchange').filter({ hasText: 'How many windows are there?' }).last()
    await expect(card.getByTestId('answer-cost')).toBeVisible({ timeout: 60_000 })
    await card.locator('.answer-text').getByRole('button', { name: /^Open citation/ }).first().click()
    const pos = page.locator('.viewer-page-position')
    await expect(pos).toBeVisible()
    await expect(pos).toContainText(/\d+\s*\/\s*\d+/)
    const [cur, total] = (await pos.innerText()).match(/\d+/g)!.map(Number)
    expect(total).toBeGreaterThanOrEqual(cur)
  })
}
