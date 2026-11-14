import { expect, test } from '@playwright/test'
import type { Viewer } from '../src/viewer3d/viewer'
import { KIND_COLORS } from '../src/lib/kind-colors'

// FIX-3: one fixed colour per item kind, on the 2D boxes and the 3D highlights, with a legend. Live API.
test.setTimeout(90_000)
test.use({ reducedMotion: 'reduce' })

const rgb = (hex: string) => { const n = parseInt(hex.slice(1), 16); return `rgb(${n >> 16}, ${(n >> 8) & 255}, ${n & 255})` }

test('3D highlights glow in the fixed colour of each kind and the legend counts them', async ({ page }) => {
  await page.goto('/?doc=colorful-11397&viewer3dTest=1#/viewer-test')
  await expect(page.getByRole('region', { name: '3D viewer', exact: true }).first()).toHaveAttribute('data-state', 'ready', { timeout: 60_000 })
  await expect.poll(() => page.evaluate(() => Boolean((window as typeof window & { viewer3dTest?: Viewer }).viewer3dTest))).toBe(true)
  const result = await page.evaluate(() => {
    const viewer = (window as typeof window & { viewer3dTest: Viewer }).viewer3dTest
    const scene = viewer.scene!
    const ids = (kind: string) => [...scene.items.keys()].filter((id) => scene.manifest.items[id].kind === kind)
    const windows = ids('window'), doors = ids('door')
    viewer.highlight([...windows, ...doors])
    const emissive = (id: string) => {
      let hex = ''
      scene.items.get(id)!.traverse((node) => {
        const mesh = node as typeof node & { isMesh?: boolean; material: { emissive?: { getHexString(): string } } }
        if (mesh.isMesh && mesh.material.emissive) hex = mesh.material.emissive.getHexString()
      })
      return hex
    }
    return { windows: windows.length, doors: doors.length, window: emissive(windows[0]), door: emissive(doors[0]) }
  })
  expect(result.windows).toBeGreaterThan(0)
  expect(result.doors).toBeGreaterThan(0)
  expect(result.window).toBe(KIND_COLORS.window.color.slice(1).toLowerCase())
  expect(result.door).toBe(KIND_COLORS.door.color.slice(1).toLowerCase())
  expect(result.window).not.toBe(result.door)
  const legend = page.getByTestId('kind-legend').first()
  await expect(legend.locator('[data-kind="window"]')).toHaveText(`Windows ${result.windows}`)
  await expect(legend.locator('[data-kind="door"]')).toHaveText(`Doors ${result.doors}`)
  await expect(legend.locator('[data-kind="window"] .kind-legend-swatch')).toHaveCSS('background-color', rgb(KIND_COLORS.window.color))
})

for (const kind of ['window', 'door'] as const) {
  test(`2D evidence boxes for ${kind}s use the ${kind} colour and a legend`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1000 })
    await page.goto('/#/chat')
    await expect(page.getByText('Connected workspace', { exact: true })).toBeVisible()
    const composer = page.getByRole('combobox', { name: 'Ask about your drawings' })
    await composer.fill('@colorful-11397')
    await page.getByRole('option').filter({ hasText: 'colorful-11397' }).click()
    await composer.fill(`How many ${kind}s are there?`)
    await page.getByRole('button', { name: 'Send question', exact: true }).click()
    await page.getByRole('button', { name: 'Open citation 1', exact: true }).first().click({ timeout: 60_000 })
    const drawing = page.getByRole('region', { name: 'Drawing viewer', exact: true })
    const boxes = drawing.locator(`.evidence-region[data-kind="${kind}"]`)
    await expect(boxes.first()).toBeVisible()
    const count = await boxes.count()
    expect(count).toBeGreaterThan(0)
    expect(await drawing.locator('.evidence-region:not(.text-highlight)').count()).toBe(count)
    await expect(boxes.first().locator('> rect')).toHaveCSS('stroke', rgb(KIND_COLORS[kind].color))
    const legend = drawing.getByTestId('kind-legend')
    await expect(legend.locator(`[data-kind="${kind}"]`)).toHaveText(`${KIND_COLORS[kind].plural} ${count}`)
    await expect(legend.locator('li')).toHaveCount(1)
  })
}
