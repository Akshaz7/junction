import { expect, test, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'

test.use({ viewport: { width: 1440, height: 900 } })
test.setTimeout(900_000)
const shots = process.env.SHOTS_DIR ?? 'test-results'
const AC = 'ifc_bench__ac20-arc'
const CC = 'cubicasa5k__colorful-11397'
const cases: [string, string, string][] = [
  ['hard1', AC, 'how many windows and doors'],
  ['hard2', CC, 'how many windows and doors'],
  ['hard3', CC, 'where are the toilets'],
  ['hard4', AC, 'remove the front door, is it still compliant?'],
  ['hard5', AC, 'what is the total floor area of the ground floor'],
  ['free1', AC, 'hw many rooms r ther on each flor'],
  ['free2', AC, 'show me all the stairs'],
  ['free3', CC, 'is there a sauna and how big is it?'],
  ['free4', AC, 'wich door is biggest'],
]

async function openChatFor(page: Page, docId: string) {
  await page.goto('/?viewer3dTest=1#/data')
  await page.getByRole('searchbox', { name: 'Search documents' }).fill(docId)
  await page.locator(`[data-doc-id="${docId}"] .data-open-file`).click()
  await page.getByRole('complementary', { name: 'Document details' }).getByRole('button', { name: 'Ask about it', exact: true }).first().click()
}

async function ask(page: Page, q: string, problems: string[], tag: string) {
  const box = page.getByRole('combobox', { name: 'Ask about your drawings' })
  await box.fill(q)
  await box.press('Enter')
  const card = page.locator('.exchange').filter({ hasText: q.slice(0, 20) }).last()
  const ok = await expect(card.getByTestId('answer-cost')).toBeVisible({ timeout: 90_000 }).then(() => true).catch(() => false)
  if (!ok) { problems.push(`${tag}: answer did not arrive`); return null }
  if (await page.getByText(/answer did not arrive|response ended before/i).count()) problems.push(`${tag}: error text shown`)
  return card
}

async function checks(page: Page, card: NonNullable<Awaited<ReturnType<typeof ask>>>, problems: string[], tag: string) {
  // 2D boxes
  const cite = card.locator('.answer-text').getByRole('button', { name: /^Open citation/ }).first()
  if (await cite.count()) {
    await cite.click()
    const drawing = page.getByRole('region', { name: 'Drawing viewer', exact: true })
    if (!await drawing.isVisible({ timeout: 8000 }).catch(() => false)) problems.push(`${tag}: citation did not open the drawing`)
    else {
      const boxes = await drawing.locator('.evidence-region').count()
      if (!boxes) problems.push(`${tag}: no 2D boxes on the drawing`)
      await page.screenshot({ path: `${shots}/${tag}-2d.png` })
      // Visualise it
      const vis = drawing.getByRole('button', { name: 'Visualise it', exact: true })
      if (await vis.isVisible().catch(() => false)) {
        await vis.click()
        const ok = await expect(drawing.getByRole('region', { name: '3D viewer', exact: true })).toHaveAttribute('data-state', 'ready', { timeout: 60_000 }).then(() => true).catch(() => false)
        if (!ok) problems.push(`${tag}: Visualise it never became ready`)
        await page.screenshot({ path: `${shots}/${tag}-3d.png` })
      } else problems.push(`${tag}: drawing has no Visualise it button`)
      await drawing.getByRole('button', { name: 'Close drawing viewer' }).click().catch(() => {})
    }
  } else problems.push(`${tag}: answer has no citation to open`)
  // Export
  const exp = card.getByRole('button', { name: /^Export/ }).first()
  if (await exp.count()) {
    await exp.click()
    const dlg = page.getByRole('dialog').filter({ hasText: 'Export site report' })
    if (!await dlg.isVisible({ timeout: 8000 }).catch(() => false)) problems.push(`${tag}: Export did not open`)
    else {
      const ready = await expect(dlg.getByRole('button', { name: /Copy|Markdown/i }).first()).toBeEnabled({ timeout: 30_000 }).then(() => true).catch(() => false)
      if (!ready) problems.push(`${tag}: Export never became ready`)
      await page.screenshot({ path: `${shots}/${tag}-export.png` })
      await dlg.getByRole('button', { name: 'Close export report' }).click()
    }
  } else problems.push(`${tag}: no Export button`)
}

test('judge flows: hard and free-form questions, 2D, 3D, export, upload', async ({ page }) => {
  const problems: string[] = []
  page.on('pageerror', (e) => problems.push(`pageerror ${e.message.slice(0, 120)}`))
  for (const [tag, doc, q] of cases) {
    await openChatFor(page, doc)
    const card = await ask(page, q, problems, tag)
    if (card) await checks(page, card, problems, tag)
  }
  // fresh upload
  await page.goto('/#/data')
  await page.getByRole('button', { name: 'Upload', exact: true }).first().click()
  const sent = page.waitForResponse((r) => r.url().endsWith('/api/upload') && r.request().method() === 'POST')
  await page.getByLabel('Choose a drawing', { exact: true }).setInputFiles({ name: `judge-${Date.now()}-generated-for-demo.png`, mimeType: 'image/png', buffer: readFileSync(new URL('./assets/upload-fixture.png', import.meta.url)) })
  if (!(await sent).ok()) problems.push('upload: POST failed')
  const dialog = page.locator('dialog.upload-dialog')
  if (!await dialog.getByRole('button', { name: /Ready/ }).isVisible({ timeout: 90_000 }).catch(() => false)) problems.push('upload: never ready')
  else {
    await dialog.getByRole('button', { name: 'Open', exact: true }).click()
    await page.getByRole('complementary', { name: 'Document details' }).getByRole('button', { name: 'Ask about it', exact: true }).first().click()
    const card = await ask(page, 'how many rooms are there', problems, 'upload')
    if (card) await checks(page, card, problems, 'upload')
  }
  expect(problems, problems.join('\n')).toEqual([])
})
