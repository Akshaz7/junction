import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'

test('dropping a drawing on the composer shows the overlay and starts the upload dialog', async ({ page }) => {
  await page.route('**/api/docs/*/ingest', (route) => route.fulfill({ json: { status: 'running', step: 'reading', progress: 0.3 } }))
  await page.goto('/#/chat')
  await expect(page.getByRole('button', { name: 'Upload a drawing' }).first()).toBeVisible()
  const bytes = readFileSync(new URL('./assets/upload-fixture.png', import.meta.url)).toString('base64')
  const transfer = await page.evaluateHandle((b64) => {
    const dt = new DataTransfer()
    dt.items.add(new File([Uint8Array.from(atob(b64), (c) => c.charCodeAt(0))], `qa-${Date.now()}-generated-for-demo.png`, { type: 'image/png' }))
    return dt
  }, bytes)
  const target = page.locator('.composer')
  await target.dispatchEvent('dragenter', { dataTransfer: transfer })
  await expect(page.getByTestId('composer-drop-overlay')).toContainText('Drop to upload and ask about it')
  await target.dispatchEvent('drop', { dataTransfer: transfer })
  await expect(page.locator('dialog.upload-dialog')).toBeVisible()
  await expect(page.locator('dialog.upload-dialog')).toContainText(/Uploading|Processing|Ready/)
})
