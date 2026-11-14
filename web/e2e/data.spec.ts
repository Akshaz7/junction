import { expect, test } from '@playwright/test'
import type { Document } from '../src/lib/types'

test('source folder opens a file with credit and passes its document to Chat', async ({ page, request }) => {
  const response = await request.get('/api/docs')
  expect(response.ok()).toBe(true)
  const grouped = await response.json() as { sources: { source: string; docs: Document[] }[] }
  const folder = grouped.sources.find((source) => source.source === 'cubicasa5k')
  expect(folder?.docs.length, 'Seed the real cubicasa5k documents before running this test').toBeGreaterThan(0)
  const doc = folder!.docs[0]
  await page.goto('/#/data')
  await expect(page.getByText('Connected workspace', { exact: true })).toBeVisible()
  await page.getByRole('searchbox', { name: 'Search documents' }).fill(doc.doc_id)
  const row = page.locator(`.data-file-row[data-doc-id="${doc.doc_id}"]`)
  await expect(row).toBeVisible()
  for (const format of doc.formats) await expect(row.getByText(format.toUpperCase(), { exact: true })).toBeVisible()
  await row.getByRole('button', { name: `Open ${doc.title}`, exact: true }).click()
  const detail = page.getByRole('complementary', { name: 'Document details' })
  await expect(detail.getByRole('heading', { name: doc.title, exact: true })).toBeVisible()
  await expect(detail.locator('.data-document-credit')).toContainText(doc.credit || 'Not provided')
  await expect(detail.locator('.data-document-credit')).toContainText(doc.licence || 'Not provided')
  await detail.getByRole('button', { name: 'Ask about it', exact: true }).click()
  await expect(page).toHaveURL(/#\/chat$/)
  await expect(page.getByLabel('Selected documents')).toContainText(doc.title)
})

// The upload and ingest-polling flow is covered live in data-changes.spec.ts.

test('a document offers its scene, handles a missing preview, and retains phone navigation on return', async ({ page }) => {
  const doc: Document = { doc_id: 'demo__scene', source: 'demo', title: 'Scene fixture, generated for demo', kind: 'ifc', formats: ['ifc'], pages: 1, licence: 'MIT', credit: 'Test fixture, generated for demo', heldout: false }
  await page.route('**/api/docs', (route) => route.fulfill({ json: { total: 1, sources: [{ source: 'demo', count: 1, docs: [doc] }] } }))
  await page.route('**/api/docs/demo__scene/files/page-1.thumb.png', (route) => route.fulfill({ status: 404, json: { status: 'not_built' } }))
  await page.route('**/api/docs/demo__scene/pages/1/image', (route) => route.fulfill({ status: 404, json: { status: 'not_built' } }))
  await page.route('**/api/docs/demo__scene/files/scene.json', (route) => route.fulfill({ json: { doc_id: doc.doc_id, glb: 'scene.glb' } }))
  await page.goto('/#/data')
  await page.getByRole('button', { name: `Open ${doc.title}`, exact: true }).click()
  const detail = page.getByRole('complementary', { name: 'Document details' })
  await expect(detail.getByRole('button', { name: 'Visualise it', exact: true })).toBeVisible()
  await expect(detail.getByText('Page preview unavailable', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Close document details' }).click()
  await page.route('**/api/docs/demo__scene/files/scene.json', (route) => route.fulfill({ status: 404, json: { status: 'not_built' } }))
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: `Open ${doc.title}`, exact: true }).click()
  expect((await detail.boundingBox())?.height).toBe(844)
  const tabs = page.getByRole('navigation', { name: 'Mobile navigation', exact: true })
  await expect(detail.getByRole('button', { name: 'Zoom in', exact: true })).toBeInViewport()
  await expect(detail.locator('.data-scene-note')).toBeHidden()
  await detail.getByLabel('Drawing credit and licence', { exact: true }).click()
  await expect(detail.locator('.data-credit-info dl')).toContainText(doc.credit!)
  await expect(detail.locator('.data-credit-info dl')).toContainText(doc.licence!)
  const visualise = detail.getByRole('button', { name: 'Visualise it', exact: true })
  await expect(visualise).toBeEnabled()
  await visualise.click()
  await expect(detail.locator('.data-mobile-scene').getByText('No 3D scene available for this document.', { exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.getByRole('button', { name: 'Close document details' }).click()
  await expect(page.getByRole('button', { name: `Open ${doc.title}`, exact: true })).toBeFocused()
  await page.getByRole('button', { name: `Open ${doc.title}`, exact: true }).click()
  await detail.getByRole('button', { name: 'Ask about it', exact: true }).click()
  await tabs.getByRole('link', { name: 'Data', exact: true }).click()
  const tabBounds = (await tabs.boundingBox())!
  const previewBounds = (await detail.boundingBox())!
  const zoomBounds = (await detail.locator('.data-zoom-controls').boundingBox())!
  expect(previewBounds.y + previewBounds.height).toBeLessThanOrEqual(tabBounds.y)
  expect(zoomBounds.y + zoomBounds.height).toBeLessThanOrEqual(tabBounds.y)
  await tabs.getByRole('link', { name: 'Chat', exact: true }).click()
  await expect(page.getByLabel('Selected documents')).toContainText(doc.title)
  await expect(page.getByRole('combobox', { name: 'Ask about your drawings' })).toBeVisible()
})

test('search spans folders and large lists use pages', async ({ page }) => {
  const docs: Document[] = Array.from({ length: 85 }, (_, n) => ({
    doc_id: `folder-a__drawing-${n}`, source: 'folder-a', title: `Drawing ${n}`, kind: 'pdf',
    formats: ['pdf'], pages: 2, licence: 'MIT', credit: 'Test fixture, generated for demo', heldout: false,
  }))
  docs.push({ ...docs[0], doc_id: 'folder-b__other', source: 'folder-b', title: 'Other folder drawing' })
  for (const doc of docs) (doc as Document & { folder?: string }).folder = doc.source
  await page.route('**/api/folders', (route) => route.fulfill({ json: { total: docs.length, folders: [
    { name: 'folder-a', path: 'folder-a', count: 85, children: [] }, { name: 'folder-b', path: 'folder-b', count: 1, children: [] },
  ] } }))
  await page.route('**/api/docs', (route) => route.fulfill({ json: { total: docs.length, sources: [
    { source: 'folder-a', count: 85, docs: docs.slice(0, 85) }, { source: 'folder-b', count: 1, docs: docs.slice(85) },
  ] } }))
  await page.goto('/#/data')
  await page.getByRole('button', { name: 'Open folder-a folder', exact: true }).click()
  await expect(page.locator('.data-file-row')).toHaveCount(40)
  await page.getByRole('button', { name: 'Next document page' }).click()
  await expect(page.getByLabel('Document pagination')).toContainText('Page 2 of 3')
  await page.getByRole('searchbox', { name: 'Search documents' }).fill('Other folder drawing')
  await expect(page.locator('.data-file-row')).toHaveCount(1)
  await expect(page.getByRole('heading', { name: 'Other folder drawing', exact: true })).toBeVisible()
  await page.getByRole('searchbox', { name: 'Search documents' }).fill('no matching document')
  await expect(page.getByText('No documents match', { exact: true })).toBeVisible()
})
