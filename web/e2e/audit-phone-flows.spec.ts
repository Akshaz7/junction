import { devices, expect, test, type Page } from '@playwright/test'
import { ask, countQuestion, rasterPick, shot } from './demo-helpers'
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
  const details = page.locator('aside.data-detail[role=dialog]') // phone: a modal sheet named by the document title (W-48)
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
        await expect(page.locator('aside.document-viewer[role=dialog]')).toBeVisible()
      }
      await openCitation()
      const viewer = page.locator('aside.document-viewer[role=dialog]')
      const box = await viewer.boundingBox()
      expect(box && box.width >= 389 && box.height >= 640, 'evidence sheet fills the screen above the composer').toBe(true)
      await page.waitForTimeout(900)
      await layoutChecks(page, audit, 'full-screen evidence')
      await shot(page, `audit-phone-${config.label}-evidence`)
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
        const panel = page.locator('aside.document-viewer[role=dialog]').first()
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
      const history = page.getByRole('dialog', { name: 'Chat history', exact: true })
      await expect(history).toBeVisible()
      await layoutChecks(page, audit, 'chat history')
      const entries = history.locator('a[href^="#/chat/"]')
      await expect(entries.first()).toBeVisible()
      if (await entries.count()) {
        await entries.first().click()
        await expect(page).toHaveURL(/#\/chat/)
        await expect(page.locator('.exchange').first()).toBeVisible({ timeout: 15_000 })
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

    test('library and tools: skill and automation run end to end, findings run, upload dialog', async ({ page }, testInfo) => {
      test.setTimeout(240_000)
      const audit = new Audit(page, `${config.label}-library-tools`)
      const docId = 'ifc_bench__ac20-arc'
      const stamp = Date.now()
      await openRoute(page, 'library')
      await layoutChecks(page, audit, 'library')
      const skills = page.getByRole('region', { name: 'Skills', exact: true })
      await page.getByRole('tab', { name: /Skills/ }).first().click().catch(() => {})
      const create = skills.getByRole('form', { name: 'Create skill' })
      await create.getByLabel('Skill name', { exact: true }).fill(`Phone audit ${stamp}`)
      await create.getByLabel('Skill prompt', { exact: true }).fill('How many windows are there?')
      await create.getByRole('button', { name: 'Save skill', exact: true }).click()
      const card = skills.locator('[data-skill-id]', { hasText: `Phone audit ${stamp}` })
      await expect(card).toBeVisible()
      await skills.getByLabel('Run on drawing', { exact: true }).selectOption(docId)
      await card.getByRole('button', { name: 'Run skill', exact: true }).click()
      await expect(skills.getByRole('region', { name: 'Skill answer' })).toBeVisible({ timeout: 30_000 })
      await layoutChecks(page, audit, 'library skill answer')
      await card.getByRole('button', { name: /Delete/ }).click()
      await expect(card).toHaveCount(0)

      await page.getByRole('tab', { name: /Automations/ }).click()
      const autos = page.getByRole('region', { name: 'Automations', exact: true })
      const form = autos.getByRole('form', { name: 'Create automation' })
      await form.getByLabel('Automation name', { exact: true }).fill(`Phone auto ${stamp}`)
      await form.getByLabel('Automation prompt', { exact: true }).fill('How many windows are there?')
      await form.getByLabel('Automation drawing', { exact: true }).selectOption(docId)
      await form.getByRole('button', { name: 'Save automation', exact: true }).click()
      const row = autos.locator('[data-automation-id]', { hasText: `Phone auto ${stamp}` })
      await expect(row).toBeVisible()
      await row.getByRole('button', { name: 'Run now', exact: true }).click()
      const report = autos.getByRole('region', { name: 'Last automation report' })
      await expect(report).toContainText('Completed', { timeout: 30_000 })
      await layoutChecks(page, audit, 'library automation report')
      const download = page.waitForEvent('download')
      await report.getByRole('button', { name: 'Export .md', exact: true }).click()
      expect((await download).suggestedFilename()).toMatch(/\.md$/)
      await row.getByRole('button', { name: /Delete automation/ }).click()
      await expect(row).toHaveCount(0)

      await openRoute(page, 'tools')
      const findings = page.getByRole('region', { name: 'Findings', exact: true })
      await findings.getByLabel('Drawing', { exact: true }).selectOption(docId)
      await findings.getByRole('button', { name: 'Run checks', exact: true }).click()
      await expect(findings.getByRole('status')).toContainText(/Checks complete|not available/, { timeout: 60_000 })
      await layoutChecks(page, audit, 'tools after run')
      const open = findings.getByRole('button', { name: /Open finding/ }).first()
      if (await open.count()) {
        await open.click()
        // findings open the 3D panel (native dialog) or the drawing sheet
        await expect(page.locator('aside.document-viewer[role=dialog], dialog.viewer3d-visualise-panel[open]').first()).toBeVisible({ timeout: 20_000 })
        await closeLayers(page, audit, 'tools finding evidence')
      }

      await openRoute(page, 'data')
      await page.getByRole('button', { name: /^Upload/ }).first().click()
      const dialog = page.getByRole('dialog', { name: 'Upload a drawing' })
      await expect(dialog).toBeVisible()
      await layoutChecks(page, audit, 'upload dialog')
      await dialog.getByRole('button', { name: 'Close upload dialog' }).click()
      await expect(dialog).toBeHidden()
      await finish(audit, testInfo)
    })
  })
}
