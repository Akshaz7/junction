import { expect, test } from '@playwright/test'
import type { LinkedViewerCanvas } from '../src/viewer3d/Viewer3D'

// These exercise the actual API and scene, including numbered evidence.
test.use({ reducedMotion: 'reduce', actionTimeout: 15_000 })
test.setTimeout(60_000)

for (const phone of [false, true]) {
  test(`${phone ? 'phone' : 'desktop'} switches 2D → 3D → 2D in one pane with the same numbered items`, async ({ page }) => {
    await page.setViewportSize(phone ? { width: 390, height: 844 } : { width: 1440, height: 1000 })
    await page.goto('/?viewer3dTest=1#/chat')
    await expect(page.getByText('Connected workspace', { exact: true })).toBeVisible()
    const composer = page.getByRole('combobox', { name: 'Ask about your drawings' })
    await composer.fill('@colorful-11397')
    await page.getByRole('option').filter({ hasText: 'colorful-11397' }).click()
    await composer.fill('How many windows are there?')
    await page.getByRole('button', { name: 'Send question', exact: true }).click()
    await page.getByRole('button', { name: 'Open citation 1', exact: true }).first().click()

    const drawing = page.getByRole(phone ? 'dialog' : 'region', { name: 'Drawing viewer', exact: true })
    const box3 = drawing.getByTestId('evidence-box-3')
    await expect(box3).toBeVisible()
    const itemId = (await box3.getAttribute('data-item-id'))!
    const labels = await drawing.locator('.evidence-region').evaluateAll((nodes) => Object.fromEntries(nodes.map((node) => [node.getAttribute('data-item-id'), node.querySelector('text')?.textContent])))
    const toggle2d = drawing.getByRole('button', { name: '2D', exact: true })
    const toggle3d = drawing.getByRole('button', { name: '3D', exact: true })
    await expect(toggle2d).toHaveAttribute('aria-pressed', 'true')
    const initial = (await drawing.getByTestId('drawing-viewport').boundingBox())!
    await drawing.getByRole('button', { name: 'Visualise it', exact: true }).click()
    const panel = drawing.getByRole('region', { name: '3D model pane', exact: true })
    const viewer = panel.getByRole('region', { name: '3D viewer', exact: true })
    await expect(viewer).toHaveAttribute('data-state', 'ready', { timeout: 30_000 })
    await expect(toggle3d).toHaveAttribute('aria-pressed', 'true')
    await expect(drawing.getByTestId('drawing-viewport')).toBeHidden()
    await expect(page.getByRole('dialog', { name: 'Visualise it', exact: true })).toHaveCount(0)
    const modelBounds = (await panel.boundingBox())!, paneBounds = (await drawing.boundingBox())!
    expect(modelBounds.x).toBeGreaterThanOrEqual(paneBounds.x)
    expect(modelBounds.x + modelBounds.width).toBeLessThanOrEqual(paneBounds.x + paneBounds.width + 1)
    expect(modelBounds.height).toBeGreaterThan(initial.height * .8)
    const state = await viewer.locator('canvas').evaluate((canvas: LinkedViewerCanvas) => canvas.__viewer3d!.state())
    for (const [id, number] of Object.entries(labels)) {
      expect(state.highlighted).toContain(id)
      expect(state.labels[id]).toBe(number)
    }
    await expect(viewer.getByLabel(`Item 3: ${itemId}`, { exact: true })).toHaveText('3')
    await expect(viewer.getByLabel('Picked item', { exact: true })).toHaveCount(0)
    await expect(viewer.getByText(/Drag to orbit|No item selected|3D view ready/)).toHaveCount(0)
    await expect(viewer.getByRole('button', { name: 'Walk', exact: true })).toBeVisible()
    if (!phone) await expect(composer).toBeVisible()

    // A pick made in 3D selects and focuses the corresponding source in 2D.
    expect(await viewer.locator('canvas').evaluate((canvas: LinkedViewerCanvas, id) => canvas.__viewer3d!.pick(id), itemId)).toBe(true)
    await toggle2d.click()
    await expect(panel).toBeHidden()
    await expect(box3).toHaveAttribute('data-linked', 'true')
    await expect(drawing.getByTestId('source-position')).toHaveText(/^Highlight 3 of /)
    await expect(drawing.getByTestId('drawing-viewport')).toBeVisible()
    expect((await drawing.getByTestId('drawing-viewport').boundingBox())!.height).toBeGreaterThanOrEqual(initial.height - 1)
    await toggle3d.click()
    await expect(viewer).toHaveAttribute('data-linked-selected', itemId)
    await toggle2d.click()
    await expect(drawing.getByTestId('drawing-viewport')).toBeVisible()
  })
}
