import { expect, test, type Page } from '@playwright/test'

/**
 * Desktop button audit. Every visible button, link, menu item and tab on every route is clicked on a fresh page,
 * and must lead somewhere real: a route change, a DOM state change, a dialog/popup/download or a 2xx network call.
 * Destructive buttons are skipped here and exercised in the end-to-end flow specs below.
 */
test.use({ viewport: { width: 1440, height: 900 } })
test.setTimeout(600_000)

const routes = ['overview', 'chat', 'compare', 'changes', 'library', 'data', 'tools', 'accuracy', 'skills', 'automations', 'findings']
const destructive = /delete|remove|trash|sign out|clear all|discard/i
const banned = /not implemented|coming soon|placeholder|lorem ipsum|todo|nothing to show yet|undefined|\[object/i
const selector = 'button:visible, a:visible, [role=menuitem]:visible, [role=tab]:visible'
const domHash = (page: Page) => page.evaluate(() => { const s = document.body.innerHTML; let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0; return `${s.length}:${h}:${location.hash}` })

async function audit(page: Page, route: string, problems: string[], seen: string[]) {
  const consoleErrors: string[] = []
  page.on('console', (m) => { if (m.type() === 'error' && !/favicon|WebSocket|ws:|Failed to load resource/i.test(m.text())) consoleErrors.push(m.text()) })
  page.on('response', (r) => { if (r.status() >= 400 && !/favicon/.test(r.url())) consoleErrors.push(`HTTP ${r.status()} ${r.url().replace(/^https?:\/\/[^/]+/, '')}`) })
  page.on('pageerror', (e) => consoleErrors.push(String(e)))
  const open = async () => { await page.goto(`/#/${route}`); await page.waitForLoadState('networkidle').catch(() => {}); await page.waitForTimeout(400) }
  await open()
  const text = await page.locator('main').innerText()
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
    try { await el.click({ timeout: 3000 }) } catch (e) { problems.push(`${who} could not be clicked: ${String(e).split('\n')[0]}`); page.off('response', onRes); continue }
    await page.waitForTimeout(900)
    await Promise.all([popup, download, dialog, chooser])
    page.off('response', onRes)
    const after = await domHash(page)
    if (bad) problems.push(`${who} network failure ${bad}`)
    if (!outcome && !reqs && after === before) {
      // A link to the current route is a legitimate no-op only when the href equals the current hash.
      if (!current && !(href && href === `#/${route}`)) problems.push(`${who} did nothing`)
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
