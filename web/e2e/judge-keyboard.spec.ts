import { expect, test } from '@playwright/test'

test.use({ viewport: { width: 1440, height: 900 } })
test.setTimeout(540_000)
const ac20 = 'ifc_bench__ac20-arc'
const long = 'I am a structural engineer reviewing this building for a renovation and I would like to understand the whole layout, so please tell me how many floors there are, how many doors and windows each floor has, which rooms are the largest, whether there are any stairs or lifts, and anything else that looks unusual or inconsistent in the drawing set. ' .repeat(3)
const questions = [
  'how many doers and windws are there',
  'What is the total floor area?',
  long,
  'and on the ground floor only?',
  'list all rooms with their areas',
  'whats the biggest room',
  'Are there any stairs? where?',
  'how many toilets',
  'compare door counts per storey in a table',
  '??? asdf qwerty',
]

test('judge types freely on desktop', async ({ page }) => {
  const problems: string[] = []
  const errors: string[] = []
  page.on('console', (m) => { if (m.type() === 'error' && !/favicon|WebSocket|Failed to load resource/i.test(m.text())) errors.push(m.text().slice(0, 160)) })
  page.on('pageerror', (e) => errors.push(`pageerror ${e.message.slice(0, 160)}`))
  await page.goto('/?viewer3dTest=1#/data')
  await page.getByRole('searchbox', { name: 'Search documents' }).fill(ac20)
  await page.locator(`[data-doc-id="${ac20}"] .data-open-file`).click()
  await page.getByRole('complementary', { name: 'Document details' }).getByRole('button', { name: 'Ask about it', exact: true }).first().click()
  const box = page.getByRole('combobox', { name: 'Ask about your drawings' })
  const exchanges = page.locator('.exchange')
  let sent = 0
  for (let i = 0; i < questions.length; i++) {
    const q = questions[i]
    await box.click()
    if (i === 2) { await box.evaluate((el, t) => { const d = new DataTransfer(); d.setData('text/plain', t); el.dispatchEvent(new ClipboardEvent('paste', { clipboardData: d, bubbles: true, cancelable: true })) }, q); }
    await box.fill(q)
    if (i === 3) { await box.press('Enter'); await box.press('Enter') } // fast double Enter
    else if (i === 7) { await page.getByRole('button', { name: 'Send question', exact: true }).dblclick().catch(() => {}) }
    else await box.press('Enter')
    sent++
    await page.waitForTimeout(400)
    const cleared = (await box.inputValue().catch(() => '')) === '' || (await box.innerText().catch(() => '')).trim() === ''
    if (!cleared) problems.push(`Q${i + 1}: composer not cleared after send`)
    const settled = await page.getByTestId('answer-cost').count()
    // wait for this answer or give up
    await expect.poll(async () => exchanges.count(), { timeout: 5000 }).toBeGreaterThanOrEqual(sent).catch(() => problems.push(`Q${i + 1}: no exchange appeared`))
    const done = await expect.poll(async () => page.locator('.status-lines').count(), { timeout: 90_000 }).toBe(0).then(() => true).catch(() => false)
    if (!done) problems.push(`Q${i + 1}: stuck on Thinking after 90 s`)
    const n = await exchanges.count()
    if (n !== sent) problems.push(`Q${i + 1}: expected ${sent} exchanges, found ${n} (double send?)`)
    if (n !== sent) sent = n
    void settled
    const ov = await page.evaluate(() => {
      const view = document.documentElement.clientWidth
      const wide = [...document.querySelectorAll('.exchange *')].filter((el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.right > view + 1 && getComputedStyle(el).visibility !== 'hidden' }).slice(0, 4).map((el) => `${el.tagName}.${(el.getAttribute('class') ?? '').slice(0, 30)}`)
      const tables = [...document.querySelectorAll('.exchange table')].filter((t) => { const p = t.closest('.exchange')!.getBoundingClientRect(); return t.getBoundingClientRect().right > p.right + 1 && !t.parentElement!.matches('[class*=scroll], [style*=overflow]') }).length
      return { wide, tables, sw: document.scrollingElement!.scrollWidth, cw: document.scrollingElement!.clientWidth }
    })
    if (ov.wide.length || ov.sw !== ov.cw || ov.tables) problems.push(`Q${i + 1}: overflow ${JSON.stringify(ov)}`)
    await page.screenshot({ path: `${process.env.SHOTS_DIR ?? 'test-results'}/judge-q${i + 1}.png` })
  }
  if (errors.length) problems.push(`console: ${[...new Set(errors)].slice(0, 4).join(' | ')}`)
  expect(problems, problems.join('\n')).toEqual([])
})
