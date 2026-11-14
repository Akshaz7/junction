import { expect, test } from '@playwright/test'
import { fidelityComparison, fidelityDocs, fidelityDrawing, fidelityFeed } from './fidelity-fixtures'
import type { ChangeFeedEntry, RuleChangeEntry } from '../src/lib/types'

const rule: RuleChangeEntry = {
  id: 'rule-change-generated-demo', type: 'rule_change', doc_a: null, doc_b: null,
  created_at: '2026-11-14T06:30:00Z', summary: {
    kind: 'rule_change', title: 'Access rule — generated for demo', url: 'https://example.org/rules/access',
    summary: 'Source text changed (generated for demo).', detected_at: '2026-11-14T06:00:00Z', source: 'context.dev',
  },
}

for (const missing of [false, true]) {
  test(`rule-source card alongside a drawing revision${missing ? ' with missing rule metadata' : ''}`, async ({ page }) => {
    const changes: ChangeFeedEntry[] = [missing ? { ...rule, summary: null, created_at: undefined } : rule, fidelityFeed[0]]
    const comparisonRequests: string[] = []
    // Feed fixtures only: the browser never posts to the authenticated watch webhook.
    await page.route('**/api/**', (route) => {
      const path = new URL(route.request().url()).pathname
      if (path === '/api/docs') return route.fulfill({ json: { sources: [{ source: 'Architecture', docs: fidelityDocs }] } })
      if (path === '/api/changes') return route.fulfill({ json: { changes } })
      if (path.startsWith('/api/changes/')) {
        comparisonRequests.push(path)
        return route.fulfill({ json: fidelityComparison })
      }
      if (path.startsWith('/api/fidelity/')) return route.fulfill({ contentType: 'image/svg+xml', body: fidelityDrawing(path.includes('previous')) })
      return route.fulfill({ status: 404, json: { detail: 'No generated fixture for this endpoint.' } })
    })
    await page.goto('/#/changes')
    const card = page.locator(`.rule-change-card[data-change-id="${rule.id}"]`)
    await expect(card).toBeVisible()
    await expect(card).toContainText('Rule source changed')
    await expect(card).toContainText('Findings rerun')
    if (missing) {
      await expect(card).toContainText('Untitled rule source')
      await expect(card).toContainText('Detected: Time unavailable')
      await expect(card).toContainText('Source link unavailable.')
      await expect(card.getByRole('link')).toHaveCount(0)
    } else {
      await expect(card).toContainText(rule.summary!.title!)
      await expect(card).toContainText(rule.summary!.summary!)
      await expect(card.locator('time')).toHaveAttribute('datetime', '2026-11-14T06:00:00.000Z')
      const source = card.getByRole('link', { name: 'View rule source' })
      await expect(source).toHaveAttribute('href', rule.summary!.url!)
      await expect(source).toHaveAttribute('target', '_blank')
      await expect(source).toHaveAttribute('rel', 'noopener noreferrer')
    }
    await card.getByText('Rule source changed', { exact: true }).click()
    await expect(page.locator('.comparison-box')).toHaveCount(0)
    await expect(page.getByRole('heading', { name: 'Nothing open', exact: true })).toBeVisible()
    expect(comparisonRequests).toEqual([])

    const revision = page.locator(`.change-row[data-change-id="${fidelityFeed[0].id}"]`)
    await expect(revision).toBeVisible()
    await expect(revision).toContainText(fidelityFeed[0].summary.title!)
    await revision.click()
    await expect(page.locator('.comparison-box')).toBeVisible()
    await expect(page.getByRole('img', { name: 'Previous revision', exact: true })).toHaveAttribute('src', fidelityComparison.v1.page_image)
    expect(comparisonRequests).toEqual([`/api/changes/${fidelityFeed[0].id}`])

    await page.getByRole('searchbox', { name: 'Search changes' }).fill(missing ? 'Untitled rule source' : 'Access rule')
    await expect(card).toBeVisible()
    await expect(revision).toHaveCount(0)
    await page.getByRole('searchbox', { name: 'Search changes' }).fill('Garden room')
    await expect(card).toHaveCount(0)
    await expect(revision).toBeVisible()
  })
}
