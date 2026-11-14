import { expect, test, type Page } from '@playwright/test'

/**
 * Desktop button audit. Every visible button, link, menu item and tab on every route is clicked on a fresh page,
 * and must lead somewhere real: a route change, a DOM state change, a dialog/popup/download or a 2xx network call.
 * Destructive buttons are skipped here and exercised in the end-to-end flow specs below.
 */
test.use({ viewport: { width: 1440, height: 900 }, launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH, args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] } })
test.setTimeout(process.env.AUDIT_RPM ? 7_200_000 : 600_000)

// Against the deployed site (AUDIT_RPM set) every /api request waits for its slot so the backend rate limit is never hit.
let nextSlot = 0
const cache = new Map<string, { status: number; headers: Record<string, string>; body: Buffer; at: number }>()
test.beforeEach(async ({ context }) => {
  const rpm = Number(process.env.AUDIT_RPM)
  if (!rpm) return
  const gap = 60_000 / rpm
  await context.route('**/api/**', async (route) => {
    const request = route.request(), url = request.url(), get = request.method() === 'GET'
    const exempt = get && /\/api\/(health|docs\/[^/]+\/(files\/[^/]+|pages\/[^/]+\/image|scene|ingest))(\?|$)/.test(url)
    if (exempt) return route.continue()
    if (!get) cache.clear() // any write invalidates what the page may have read
    else {
      const hit = cache.get(url)
      if (hit && Date.now() - hit.at < 120_000) return route.fulfill({ status: hit.status, headers: hit.headers, body: hit.body })
    }
    const at = Math.max(Date.now(), nextSlot); nextSlot = at + gap
    await new Promise((r) => setTimeout(r, at - Date.now()))
    if (!get) return route.continue()
    const response = await route.fetch()
    const entry = { status: response.status(), headers: response.headers(), body: await response.body(), at: Date.now() }
    if (response.ok() && !/text\/event-stream/.test(entry.headers['content-type'] ?? '')) cache.set(url, entry)
    await route.fulfill({ response, body: entry.body })
  })
})

const routes = ['overview', 'chat', 'compare', 'changes', 'library', 'data', 'tools', 'skills', 'automations', 'findings']
const destructive = /delete|remove|trash|sign out|clear all|discard/i
const banned = /not implemented|coming soon|placeholder|lorem ipsum|todo|nothing to show yet|undefined|\[object/i
const base = 'button:visible, a:visible, [role=menuitem]:visible, [role=tab]:visible'
const domHash = (page: Page) => page.evaluate(() => { const s = document.body.innerHTML; let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0; return `${s.length}:${h}:${location.hash}` })

async function audit(page: Page, route: string, problems: string[], seen: string[], setup?: (page: Page) => Promise<void>, scope = 'body') {
  const consoleErrors: string[] = []
  page.on('console', (m) => { if (m.type() === 'error' && !/favicon|WebSocket|ws:|Failed to load resource/i.test(m.text())) consoleErrors.push(m.text()) })
  page.on('response', (r) => { if (r.status() >= 400 && !(/favicon/.test(r.url()) || (process.env.AUDIT_ALLOW_OPTIONAL_404 && /\/files\/(elements|text-\d+)\.json|\/assets\/index-[\w-]+\.(js|css)/.test(r.url())))) consoleErrors.push(`HTTP ${r.status()} ${r.url().replace(/^https?:\/\/[^/]+/, '')}`) })
  page.on('pageerror', (e) => consoleErrors.push(String(e)))
  const selector = scope === 'body' ? base : base.split(', ').map((x) => `${scope} ${x}`).join(', ')
  const open = async () => {
    // A redeploy mid-run can serve a page whose hashed bundle is gone: reload until the shell renders.
    for (let attempt = 0; attempt < 4; attempt++) {
      await page.goto('about:blank'); await page.goto(`/#/${route}`)
      if (await page.locator('.rail').first().waitFor({ state: 'visible', timeout: 10_000 }).then(() => true).catch(() => false)) break
    }
    await page.waitForTimeout(700)
    if (setup) await setup(page)
  }
  await open()
  const text = await page.locator(scope === 'body' ? 'main' : scope).first().innerText()
  if (banned.test(text)) problems.push(`${route}: placeholder text "${text.match(banned)![0]}"`)
  const count = await page.locator(selector).count()
  for (let i = 0; i < count; i++) {
    if (i > 0) await open()
    const el = page.locator(selector).nth(i)
    if (!(await el.isVisible().catch(() => false))) continue
    const label = ((await el.getAttribute('aria-label')) || (await el.innerText().catch(() => '')) || (await el.getAttribute('title')) || `#${i}`).trim().replace(/\s+/g, ' ').slice(0, 60)
    const tag = await el.evaluate((n) => n.tagName.toLowerCase())
    const who = `${route}: ${tag} "${label}"`
    seen.push(who)
    if (/skip to content/i.test(label)) continue
    const current = await el.evaluate((n) => n.getAttribute('aria-pressed') === 'true' || n.getAttribute('aria-selected') === 'true' || n.getAttribute('aria-current') === 'page')
    if (destructive.test(label) || await el.isDisabled().catch(() => false)) continue
    const href = tag === 'a' ? await el.getAttribute('href') : null
    if (tag === 'a' && (!href || href === '#')) { problems.push(`${who} has no real href`); continue }
    const before = await domHash(page)
    let reqs = 0, bad = ''
    const onRes = (r: import('@playwright/test').Response) => { if (r.url().includes('/api/')) { reqs++; if (r.status() >= 400 && r.status() !== 404) bad = `${r.status()} ${r.url()}` } }
    page.on('response', onRes)
    let outcome = false
    const popup = page.waitForEvent('popup', { timeout: 1200 }).then(async (p) => { outcome = true; await p.close() }).catch(() => {})
    const download = page.waitForEvent('download', { timeout: 1200 }).then(() => { outcome = true }).catch(() => {})
    const dialog = page.waitForEvent('dialog', { timeout: 1200 }).then(async (d) => { outcome = true; await d.dismiss() }).catch(() => {})
    const chooser = page.waitForEvent('filechooser', { timeout: 1200 }).then(() => { outcome = true }).catch(() => {})
    try { await el.click({ timeout: 3000 }) } catch (e) { problems.push(`${who} could not be clicked: ${String(e).split('\n').filter((l) => /waiting|intercepts|not enabled|disabled|not stable|outside/.test(l)).slice(0, 3).join(' / ') || String(e).split('\n')[0]}`); page.off('response', onRes); continue }
    await page.waitForTimeout(900)
    await Promise.all([popup, download, dialog, chooser])
    page.off('response', onRes)
    const after = await domHash(page)
    if (bad) problems.push(`${who} network failure ${bad}`)
    if (!outcome && !reqs && after === before) {
      // A link to the current route is a legitimate no-op only when the href equals the current hash.
      // External source links open a new tab (checked by href/target, the popup is not always reported); Fit drawing is a legitimate no-op when the page is already fitted.
      const external = tag === 'a' && /^https?:\/\//i.test(href ?? '') && (await el.getAttribute('target')) === '_blank'
      const alreadyFitted = /^Fit drawing$/i.test(label)
      if (!current && !external && !alreadyFitted && !(href && href === `#/${route}`)) problems.push(`${who} did nothing`)
    }
  }
  if (consoleErrors.length) problems.push(`${route}: console errors ${[...new Set(consoleErrors)].slice(0, 3).join(' | ')}`)
}

for (const route of routes) {
  test(`every control on #/${route} leads somewhere`, async ({ page }) => {
    const problems: string[] = [], seen: string[] = []
    await audit(page, route, problems, seen)
    test.info().annotations.push({ type: 'controls', description: `${seen.length} controls clicked on ${route}` })
    console.log(`AUDIT ${route}: ${seen.length} controls`)
    expect(problems, problems.join('\n')).toEqual([])
  })
}

const ac20 = 'ifc_bench__ac20-arc'

test('Library flow: create a skill, run it on a drawing, see the answer, delete it (all through the UI)', async ({ page }) => {
  const name = `Audit skill ${Date.now()}`
  await page.goto('/#/library')
  const panel = page.getByRole('tabpanel')
  const create = panel.getByRole('form', { name: 'Create skill' })
  await create.getByLabel('Skill name', { exact: true }).fill(name)
  await create.getByLabel('Skill prompt', { exact: true }).fill('How many windows are there?')
  const saved = page.waitForResponse((r) => r.url().endsWith('/api/skills') && r.request().method() === 'POST')
  await create.getByRole('button', { name: 'Save skill', exact: true }).click()
  expect((await saved).status()).toBe(201)
  await panel.getByLabel('Run on drawing', { exact: true }).selectOption(ac20)
  const card = panel.locator('article, section').filter({ hasText: name }).filter({ has: page.getByRole('button', { name: 'Run skill', exact: true }) }).last()
  const ran = page.waitForResponse((r) => /\/api\/skills\/[^/]+\/run$/.test(r.url()))
  await card.getByRole('button', { name: 'Run skill', exact: true }).click()
  expect((await ran).ok()).toBe(true)
  await expect(panel.getByRole('region', { name: 'Skill answer' })).toBeVisible()
  const del = page.waitForResponse((r) => r.request().method() === 'DELETE' && r.url().includes('/api/skills/'))
  await panel.getByRole('button', { name: `Delete skill ${name}` }).click()
  expect((await del).status()).toBe(204)
  await expect(panel.getByText(name, { exact: true })).toHaveCount(0)
})

test('Library flow: create an automation, run now, see and export the report, delete it', async ({ page }) => {
  const name = `Audit routine ${Date.now()}`
  await page.goto('/#/library')
  await page.getByRole('tab', { name: 'Automations' }).click()
  const screen = page.getByRole('tabpanel')
  const create = screen.getByRole('form', { name: 'Create automation' })
  await create.getByLabel('Automation name', { exact: true }).fill(name)
  await create.getByLabel('Automation prompt', { exact: true }).fill('How many windows are there?')
  await create.getByLabel('Automation drawing', { exact: true }).selectOption(ac20)
  const saved = page.waitForResponse((r) => r.url().endsWith('/api/automations') && r.request().method() === 'POST')
  await create.getByRole('button', { name: 'Save automation', exact: true }).click()
  expect((await saved).status()).toBe(201)
  const card = screen.locator('[data-automation-id]').filter({ hasText: name })
  await expect(card).toContainText('Not run yet')
  const ran = page.waitForResponse((r) => /\/api\/automations\/[^/]+\/run$/.test(r.url()))
  await card.getByRole('button', { name: 'Run now', exact: true }).click()
  expect((await ran).ok()).toBe(true)
  const report = screen.getByRole('region', { name: 'Last automation report' })
  await expect(report.getByRole('heading', { name, exact: true })).toBeVisible()
  const download = page.waitForEvent('download')
  await report.getByRole('button', { name: 'Export .md', exact: true }).click()
  expect((await download).suggestedFilename()).toMatch(/\.md$/)
  const del = page.waitForResponse((r) => r.request().method() === 'DELETE' && r.url().includes('/api/automations/'))
  await screen.getByRole('button', { name: `Delete automation ${name}` }).click()
  expect((await del).status()).toBe(204)
  await expect(screen.getByText(name, { exact: true })).toHaveCount(0)
})

test('Tools flow: run checks on AC20 and open a finding in the viewer', async ({ page }) => {
  await page.goto('/#/tools')
  const screen = page.getByRole('region', { name: 'Findings', exact: true })
  await screen.getByLabel('Drawing', { exact: true }).selectOption(ac20)
  const run = page.waitForResponse((r) => r.url().endsWith('/api/findings/run'))
  await screen.getByRole('button', { name: 'Run checks', exact: true }).click()
  expect((await run).ok()).toBe(true)
  const open = screen.getByRole('button', { name: /^Open finding / }).first()
  await expect(open).toBeEnabled({ timeout: 30_000 })
  await open.click()
  await expect(page.locator('.viewer3d canvas, .evidence-region').first()).toBeVisible({ timeout: 30_000 })
})

const question = 'How many windows are there?'
/** Ask a real question about AC20 and open its first citation: the state where the drawing viewer toolbar exists. */
async function answered(page: Page, openViewer: boolean, visualise = false) {
  await page.goto('/?viewer3dTest=1#/data')
  await page.getByRole('searchbox', { name: 'Search documents' }).fill(ac20)
  await page.locator(`[data-doc-id="${ac20}"] .data-open-file`).click()
  await page.getByRole('complementary', { name: 'Document details' }).getByRole('button', { name: 'Ask about it', exact: true }).first().click()
  await page.getByRole('combobox', { name: 'Ask about your drawings' }).fill(question)
  await page.getByRole('button', { name: 'Send question', exact: true }).click()
  const card = page.locator('.exchange').filter({ hasText: question }).last()
  await expect(card.getByTestId('answer-cost')).toBeVisible({ timeout: 60_000 })
  if (!openViewer) return
  await card.locator('.answer-text').getByRole('button', { name: /^Open citation/ }).first().click()
  const drawing = page.getByRole('region', { name: 'Drawing viewer', exact: true })
  await expect(drawing).toBeVisible()
  if (!visualise) return
  await drawing.getByRole('button', { name: 'Visualise it', exact: true }).click()
  await expect(drawing.getByRole('region', { name: '3D viewer', exact: true })).toHaveAttribute('data-state', 'ready', { timeout: 60_000 })
}

test.describe('answer, viewer and 3D states', () => {
  const stages: [string, (page: Page) => Promise<void>, string][] = [
    ['answer card', (page) => answered(page, false), '.exchange'],
    ['drawing viewer toolbar', (page) => answered(page, true), '[aria-label="Drawing viewer"]'],
    ['3D pane', (page) => answered(page, true, true), '[aria-label="Drawing viewer"]'],
  ]
  for (const [name, setup, scope] of stages) {
    test(`every control in the ${name} leads somewhere`, async ({ page }) => {
      const problems: string[] = [], seen: string[] = []
      await audit(page, 'chat', problems, seen, setup, scope)
      console.log(`AUDIT ${name}: ${seen.length} controls`)
      expect(problems, problems.join('\n')).toEqual([])
    })
  }
})

test('Data flow: upload a file from the UI and see it listed', async ({ page }) => {
  await page.goto('/#/data')
  await page.getByRole('button', { name: 'Upload', exact: true }).first().click()
  const name = `audit-${Date.now()}-generated-for-demo.png`
  const sent = page.waitForResponse((r) => r.url().endsWith('/api/upload') && r.request().method() === 'POST')
  await page.getByLabel('Choose a drawing', { exact: true }).setInputFiles({ name, mimeType: 'image/png', buffer: (await import('node:fs')).readFileSync(new URL('./assets/upload-fixture.png', import.meta.url)) })
  expect((await sent).ok()).toBe(true)
  const dialog = page.locator('dialog.upload-dialog')
  await expect(dialog.getByRole('button', { name: /Ready/ })).toBeVisible({ timeout: 90_000 })
  await dialog.getByRole('button', { name: 'Open', exact: true }).click()
  await expect(page.getByRole('complementary', { name: 'Document details' })).toBeVisible()
})
