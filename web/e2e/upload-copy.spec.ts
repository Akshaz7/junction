import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'

// The real upload runs; only the processing status read is replaced, to reproduce a server-side failure and a 3D stage.
test('the upload dialog shows plain stage names and hides raw errors behind details', async ({ page }) => {
  let polls = 0
  await page.route('**/api/docs/*/ingest', async (route) => {
    polls++
    await route.fulfill(polls < 2
      ? { json: { status: 'running', step: 'usdz', progress: 0.8 } }
      : { json: { status: 'failed', reason: 'RuntimeError: usdz conversion produced no geometry' } })
  })
  await page.goto('/#/data')
  await page.getByRole('button', { name: 'Upload', exact: true }).first().click()
  await page.getByLabel('Choose a drawing', { exact: true }).setInputFiles({ name: `qa-${Date.now()}-generated-for-demo.png`, mimeType: 'image/png', buffer: readFileSync(new URL('./assets/upload-fixture.png', import.meta.url)) })
  const dialog = page.locator('dialog.upload-dialog')
  await expect(dialog).toContainText('Preparing AR model')
  await expect(dialog.getByRole('alert')).toContainText('This file has no 3D geometry we can convert.', { timeout: 15_000 })
  await expect(dialog.getByRole('alert').locator('p')).not.toContainText('RuntimeError')
  await expect(dialog.locator('pre')).toBeHidden()
  await dialog.getByText('Details', { exact: true }).click()
  await expect(dialog.locator('pre')).toContainText('RuntimeError')
})
