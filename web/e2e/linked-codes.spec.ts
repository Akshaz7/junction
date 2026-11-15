import { expect, test } from '@playwright/test'
import { ac20, api, ask, selectFromData } from './demo-helpers'
import type { Document } from '../src/lib/types'
import { propertyValue, type LinkedItem } from '../src/lib/linked'
import { sourceProps } from '../src/lib/item-measures'

// All documents, answers, page images and item details come from the real API.
for (const phone of [false, true]) {
  test(`door codes open sourced item details and return focus (${phone ? 'phone' : 'desktop'})`, async ({ page }) => {
    test.setTimeout(60_000)
    await page.setViewportSize(phone ? { width: 390, height: 844 } : { width: 1440, height: 1000 })
    const metadata = await page.request.get(`${api}/api/docs/${ac20}`)
    expect(metadata.ok()).toBe(true)
    const doc = await metadata.json() as Document
    let planDoor: string | undefined
    for (let p = 1; p <= doc.pages && !planDoor; p++) {
      const response = await page.request.get(`${api}/api/docs/${ac20}/planmap/${p}`)
      if (response.status() === 404) continue
      expect(response.ok()).toBe(true)
      const map = await response.json() as { items: { item_id: string; kind: string; bbox_px: number[] | null }[] }
      planDoor = map.items.find((entry) => entry.kind === 'door' && entry.bbox_px)?.item_id
    }
    await page.goto('/#/data')
    await expect(page.getByText('Connected workspace', { exact: true })).toBeVisible()
    await selectFromData(page, doc, phone)
    const fallback = planDoor ? null : await ask(page, 'What is the narrowest door width used here?', ac20)
    const itemId = planDoor ?? fallback?.answer.citations[0]?.item_ids[0]
    expect(itemId, 'A real door must be identified by the plan or answer evidence').toBeTruthy()
    const response = await page.request.get(`${api}/api/docs/${ac20}/items/${encodeURIComponent(itemId!)}`)
    expect(response.ok()).toBe(true)
    const item = await response.json() as LinkedItem
    expect(item.kind).toBe('door')
    expect(item.storey).toBeTruthy()
    expect(item.type_name).toBeTruthy()
    expect(Object.keys(item.props).length).toBeGreaterThan(0)
    if (planDoor) {
      // The existing tag control opens this door's actual storey plan through /planmap.
      expect(item.tag).toBeTruthy()
      const { answer, card } = await ask(page, `show ${item.tag}`, ac20)
      expect(answer.evidence.scene.highlight_item_ids).toContain(itemId)
      await card.getByRole('button', { name: `Show ${item.tag} on drawing`, exact: true }).click()
    } else {
      const citation = fallback!.answer.citations.find((source) => source.item_ids.includes(itemId!))
      expect(citation).toBeTruthy()
      await fallback!.card.locator('.answer-text').getByRole('button', { name: `Open citation ${citation!.n}`, exact: true }).click()
    }
    const viewer = page.getByRole(phone ? 'dialog' : 'region', { name: 'Drawing viewer', exact: true })
    const trigger = viewer.locator(`.evidence-region[data-item-id="${itemId}"]`)
    await expect(trigger).toBeVisible()
    await trigger.focus()
    await trigger.press('Enter')
    const details = page.getByRole(phone ? 'dialog' : 'region', { name: 'Item details', exact: true })
    await expect(details).toBeVisible()
    await expect(details.locator('[data-field="storey"]')).toHaveText(item.storey!)
    await expect(details.locator('[data-field="type"]')).toHaveText(item.type_name!)
    await expect(details.locator('[data-field="tag"]')).toHaveText(item.tag || 'Not supplied')
    expect(await details.locator('[data-property]').evaluateAll((nodes) => nodes.map((node) => [
      node.querySelector('dt')?.textContent, node.querySelector('dd')?.textContent,
    ]))).toEqual(Object.entries(sourceProps(item.props)).map(([key, value]) => [key, propertyValue(value)]))
    if (phone) {
      await expect(details).toHaveAttribute('aria-modal', 'true')
      const bounds = await details.boundingBox()
      expect(bounds!.y + bounds!.height).toBeCloseTo(844, 0)
    }
    await details.getByRole('button', { name: 'Close item details', exact: true }).press('Escape')
    await expect(details).toHaveCount(0)
    await expect(trigger).toBeFocused()
    // The visible numbered label and tag share the same clickable item target.
    await trigger.locator('svg').first().click()
    await expect(details.locator('[data-field="name"]')).toHaveText(item.name || 'Not supplied')
    await details.getByRole('button', { name: 'Close item details', exact: true }).click()
    await expect(trigger).toBeFocused()
    await trigger.press('Enter')
    const place = item.places[0]
    expect(place, 'The door must have a real plan location').toBeTruthy()
    await details.locator('.item-places button').first().click()
    if (phone) await expect(details).toHaveCount(0)
    await expect(viewer.locator('.page-number')).toHaveText(String(place.page))
    const focusedBox = viewer.locator('.evidence-region').first()
    await expect(focusedBox).toHaveAttribute('data-item-id', item.item_id)
    await expect.poll(async () => {
      const region = await focusedBox.boundingBox(), viewport = await viewer.getByTestId('drawing-viewport').boundingBox()
      return !!region && !!viewport && region.width > 0 && region.height > 0
        && region.x >= viewport.x - 1 && region.y >= viewport.y - 1
        && region.x + region.width <= viewport.x + viewport.width + 1
        && region.y + region.height <= viewport.y + viewport.height + 1
    }).toBe(true)
  })
}
