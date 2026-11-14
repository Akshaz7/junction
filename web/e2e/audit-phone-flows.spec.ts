import { devices, expect, test, type Page } from '@playwright/test'
import { ask, countQuestion, rasterPick } from './demo-helpers'
import { Audit, closeLayers, crawlScope, installSafeAreas, layoutChecks, openRoute } from './audit-phone'
import type { Document } from '../src/lib/types'

/** Phone end-to-end flows behind the buttons: chat, evidence, 3D, history, data, changes, library, tools, upload. */
const { defaultBrowserType: _ignored, ...iphone } = devices['iPhone 15 Pro Max']
const configs = [
  { label: 'iphone15promax', use: { ...iphone, viewport: { width: 430, height: 932 } } },
  { label: 'viewport390', use: { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true } },
]

async function finish(audit: Audit, testInfo: Parameters<Audit['report']>[0]) {
  await audit.report(testInfo)
  expect.soft(audit.unexpectedConsole(), 'console errors').toEqual([])
  expect(audit.findings).toEqual([])
}

const tabs = (page: Page) => page.getByRole('navigation', { name: 'Mobile navigation', exact: true })

async function openDocInChat(page: Page, doc: Document) {
  await openRoute(page, 'data')
  await page.getByRole('searchbox', { name: 'Search documents' }).fill(doc.doc_id)
  await page.locator(`[data-doc-id="${doc.doc_id}"] .data-open-file`).click()
  const details = page.getByRole('complementary', { name: 'Document details' })
  await expect(details).toBeVisible()
  await details.getByRole('button', { name: 'Ask about it', exact: true }).first().click()
  await expect(page).toHaveURL(/#\/chat/)
  await expect(page.getByLabel('Selected documents')).toContainText(doc.title)
}

for (const config of configs) {
  test.describe(`phone flows ${config.label}`, () => {
    test.use({ ...config.use, permissions: ['clipboard-read', 'clipboard-write'] })
    test.beforeEach(async ({ page }) => {
      await installSafeAreas(page)
      await page.addInitScript(() => { Object.defineProperty(navigator, 'share', { value: async (data: unknown) => { (window as unknown as { __shared: unknown }).__shared = data }, configurable: true }) })
    })

    test('chat: ask, citation, full-screen evidence, 3D and back; New, History, Share', async ({ page }, testInfo) => {
      test.setTimeout(240_000)
      const audit = new Audit(page, `${config.label}-chat-flow`)
      const raster = await rasterPick(page)
      await openDocInChat(page, raster.doc)
      await layoutChecks(page, audit, 'chat (document selected)')
      const { answer, card } = await ask(page, countQuestion, raster.doc.doc_id)
      await layoutChecks(page, audit, 'chat (answer)')
      const chatUrl = page.url()
      expect(chatUrl).toMatch(/chat=/)
      const reopen = async () => {
        await page.goto(chatUrl); await page.reload()
        await expect(page.locator('.exchange .answer-text').first()).toBeVisible({ timeout: 15_000 })
      }

      // Every control in the answer card.
      await crawlScope(page, audit, 'answer card', reopen, '.exchange', { skip: /show on table|speak|listen|download/i })

      // Citation → full-screen evidence → every control → close.
      const openCitation = async () => {
        await reopen()
        await page.getByRole('button', { name: `Open citation ${answer.citations[0].n}`, exact: true }).first().click()
        await expect(page.getByRole('dialog', { name: 'Drawing viewer', exact: true })).toBeVisible()
      }
      await openCitation()
      const viewer = page.getByRole('dialog', { name: 'Drawing viewer', exact: true })
      const box = await viewer.boundingBox()
      expect(box && box.width >= 389 && box.height >= 800, 'evidence sheet is full screen').toBe(true)
      await layoutChecks(page, audit, 'full-screen evidence')
      await crawlScope(page, audit, 'evidence viewer', openCitation, '[role=dialog][aria-label="Drawing viewer"]', { skip: /download|open source/i, max: 40 })
      await openCitation()
      await viewer.getByRole('button', { name: 'Close drawing viewer', exact: true }).click()
      await expect(viewer).toHaveCount(0)
      await expect(tabs(page).getByRole('link', { name: 'Chat', exact: true })).toBeInViewport()

      // 3D: Visualise it from the answer card, then back.
      await reopen()
      const visualise = card.getByRole('button', { name: 'Visualise it', exact: true }).or(page.getByRole('button', { name: 'Visualise it', exact: true })).first()
      if (await visualise.count()) {
        await visualise.click()
        const panel = page.getByRole('dialog', { name: /Visualise it|Drawing viewer|3D/ }).first()
        await expect(panel).toBeVisible()
        await expect(page.getByRole('region', { name: '3D viewer', exact: true })).toBeVisible({ timeout: 20_000 })
        await layoutChecks(page, audit, '3D view')
        await page.getByRole('button', { name: /Close 3D view|Close drawing viewer/ }).first().click()
        await expect(page.getByRole('region', { name: '3D viewer', exact: true })).toHaveCount(0)
        await expect(tabs(page).getByRole('link', { name: 'Chat', exact: true })).toBeInViewport()
      } else audit.add('chat > answer', 'dead-end', 'no Visualise it entry point for a document with a 3D scene')

      // New / History / Share.
      await reopen()
      const header = page.locator('.pagebar')
      await header.getByRole('button', { name: 'History' }).click()
      const history = page.getByRole('dialog', { name: /history/i }).or(page.locator('.chat-history, [aria-label*="history" i]')).first()
      await expect(history).toBeVisible()
      await layoutChecks(page, audit, 'chat history')
      const entries = history.getByRole('button').or(history.getByRole('link'))
      if (await entries.count()) {
        await entries.first().click()
        await expect(page).toHaveURL(/chat=/)
      } else audit.add('chat > History', 'dead-end', 'history opened with nothing to pick')
      await reopen()
      await header.getByRole('button', { name: 'Share' }).or(page.getByRole('button', { name: /share/i })).first().click()
      // On a phone Share opens the native share sheet; the stub records what would be shared.
      await expect.poll(() => page.evaluate(() => (window as unknown as { __shared?: { url: string } }).__shared?.url ?? '')).toMatch(/#\/chat\/[^/]+$/)
      await header.getByRole('button', { name: 'New chat' }).click()
      await expect(page.locator('.exchange .answer-text')).toHaveCount(0)
      await expect(page.getByRole('combobox', { name: 'Ask about your drawings' })).toBeVisible()
      await closeLayers(page, audit, 'chat flow end')
      await finish(audit, testInfo)
    })
  })
}
