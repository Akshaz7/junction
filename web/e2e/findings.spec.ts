import { expect, test } from '@playwright/test'
import type { Finding } from '../src/lib/findings'
import type { LinkedViewerCanvas } from '../src/viewer3d/Viewer3D'

test.use({ reducedMotion: 'reduce', launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH, args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] } })

test('real AC20 checks show the sourced fire-exit rule and open its exact item evidence', async ({ page }) => {
  test.setTimeout(60_000)
  const docId = 'ifc_bench__ac20-arc'
  await page.goto('/?viewer3dTest=1#/findings')
  const screen = page.getByRole('region', { name: 'Findings', exact: true })
  const picker = screen.getByLabel('Drawing', { exact: true })
  await expect(picker.locator(`option[value="${docId}"]`)).toHaveCount(1)
  await picker.selectOption(docId)
  const responsePromise = page.waitForResponse((response) => response.url().endsWith('/api/findings/run') && response.request().method() === 'POST')
  await screen.getByRole('button', { name: 'Run checks', exact: true }).click()
  const response = await responsePromise
  expect(response.ok()).toBe(true)
  const result = await response.json() as { status: string; findings: Finding[] }
  expect(result.status).toBe('ok')
  const finding = result.findings.find((entry) => entry.rule_id === 'fi-fire-exits-per-storey')!
  expect(finding).toBeTruthy()
  expect(finding.item_ids.length).toBeGreaterThan(0)
  const row = screen.locator(`[data-finding-id="${finding.id}"]`)
  await expect(row.locator('blockquote').first()).toHaveText(finding.rule.text)
  if (finding.rule.source_title) await expect(row).toContainText(finding.rule.source_title)
  const open = row.getByRole('button', { name: `Open finding ${finding.rule_id}`, exact: true })
  await expect(open).toBeEnabled({ timeout: 20_000 })
  await open.click()
  await expect.poll(async () => {
    const boxes = await page.locator('.evidence-region title').allTextContents()
    if (finding.item_ids.some((id) => boxes.includes(id))) return true
    return page.evaluate((ids) => {
      const viewer = document.querySelector<LinkedViewerCanvas>('.viewer3d canvas')?.__viewer3d
      return ids.every((id) => viewer?.state().highlighted.includes(id) ?? false)
    }, finding.item_ids)
  }, { timeout: 30_000 }).toBe(true)
})
