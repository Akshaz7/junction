import { expect, test } from '@playwright/test'
import type { Viewer } from '../src/viewer3d/viewer'

test.setTimeout(150_000)
test('revised plan from a removed door', async ({ page }) => {
  await page.goto('/?doc=cubicasa5k__colorful-11397&viewer3dTest=1#/viewer-test')
  await expect(page.getByRole('region', { name: '3D viewer', exact: true }).first()).toHaveAttribute('data-state', 'ready', { timeout: 90_000 })
  const button = page.getByRole('button', { name: 'Revised plan' })
  await expect(button).toBeDisabled()
  await page.evaluate(() => {
    const v = (window as unknown as { viewer3dTest: Viewer }).viewer3dTest
    v.applyCommand({ op: 'hide', item_ids: ['door-001', 'door-002'] })
  })
  await expect(button).toBeEnabled()
  await button.click()
  const canvas = page.getByTestId('revised-plan-canvas')
  await expect(canvas).toBeVisible({ timeout: 30_000 })
  await expect(page.getByTestId('revised-plan-dialog')).toContainText('generated from 3D edits')
  await page.waitForTimeout(500)
  await page.screenshot({ path: '../results/qa/shots/revised-plan.png' })
})
