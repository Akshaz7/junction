import { readFileSync } from 'node:fs'
import { test, expect, production, chooseDocument, openDocument, chatFor, ask, savedAnswer, viewerState } from './final-helpers'

test.use({ viewport: { width: 1440, height: 1000 } })
test.setTimeout(180_000) // LONG: live answers and real geometry, one browser/worker.

for (const [label, kind] of [['drawing', 'dxf'], ['model', 'ifc'], ['scan', 'raster']]) {
  test(`[WEB] Library browses, searches and opens a real ${label}; selection stays reachable`, async ({ page, request }) => {
    const doc = await chooseDocument(request, kind)
    test.info().annotations.push({ type: 'document', description: `${doc.doc_id} (${doc.source})` })
    const { detail, selected, search } = await openDocument(page, doc)
    await expect(detail.getByRole('heading').first()).toContainText(doc.title)
    // The details panel must leave the active picker button clickable, with its selected state visible.
    await selected.locator('.data-open-file').click({ trial: true })
    await expect(search).toBeVisible()
    const image = detail.locator('.data-preview img')
    await expect(image).toBeVisible()
    await expect.poll(() => image.evaluate((n) => (n as HTMLImageElement).naturalWidth)).toBeGreaterThan(0)
    if (kind === 'ifc') {
      await detail.getByRole('button', { name: '3D', exact: true }).click()
      await expect(detail.getByRole('region', { name: '3D viewer', exact: true })).toHaveAttribute('data-state', 'ready', { timeout: 90_000 })
    }
    await page.screenshot({ path: test.info().outputPath(`${label}-open.png`) })
    await detail.getByRole('button', { name: 'Close document details', exact: true }).click()
    await search.fill('e2e-no-such-drawing-7fc291')
    await expect(page.getByText('No documents match', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Clear search', exact: true }).click()
    await expect(page.locator('.data-file-row').first()).toBeVisible()
    const folders = page.getByRole('navigation', { name: 'Document folders' })
    await folders.getByRole('button', { name: /^Open .+ folder$/ }).first().click()
    await expect(page.locator('.data-file-row').first()).toBeVisible()
  })
}

test('[ENGINE] Chat shows live status, bold answer, citations, evidence steps and confidence', async ({ page, request }) => {
  let answer
  if (production) answer = await savedAnswer(page, request)
  else {
    await chatFor(page, await chooseDocument(request, 'dxf'))
    answer = await ask(page, 'How many doors and windows are there?')
  }
  const card = page.getByTestId('answer-card').filter({ hasText: answer.question }).first()
  await expect.soft(card.locator('.answer-text strong').first(), 'The answer opens with a bold key fact').toBeVisible()
  await expect.soft(card.locator('.answer-text li'), 'At most four short bullets').toHaveCount(Math.min(await card.locator('.answer-text li').count(), 4))
  expect.soft(answer.citations.length, 'Answer contains source citations').toBeGreaterThan(0)
  const evidence = card.getByRole('region', { name: 'How we know', exact: true })
  await expect.soft(evidence).toBeVisible()
  expect.soft(await evidence.locator('li').count(), 'Evidence gives checkable steps').toBeGreaterThan(0)
  await expect.soft(evidence.locator('.evidence-pill')).toHaveText(/^(Verified|Cross-checked|Estimate) · \d+(?:\.\d+)?%$/)
  await card.locator('.sources-summary').click()
  await expect(card.locator('.sources-detail')).toHaveAttribute('open', '')
  await expect(card.locator('.sources-detail .citation-chip').first()).toBeVisible()
  const citation = answer.citations.find((c) => answer.evidence.boxes.some((b) => b.page === c.page && c.item_ids.includes(b.item_id))) ?? answer.citations[0]
  await card.locator('.sources-detail').getByRole('button', { name: `Open citation ${citation.n}`, exact: true }).click()
  const viewer = page.getByRole('region', { name: 'Drawing viewer', exact: true })
  await expect(viewer).toBeVisible()
  const boxed = answer.evidence.boxes.filter((b) => b.page === citation.page)
  expect.soft(boxed.length, 'Count evidence supplies drawing boxes').toBeGreaterThan(0)
  if (boxed.length) {
    await expect.poll(() => viewer.locator('svg.drawing-evidence g[data-item-id]').count()).toBeGreaterThan(0)
    const ids = await viewer.locator('svg.drawing-evidence g[data-item-id]').evaluateAll((nodes) => nodes.map((n) => n.getAttribute('data-item-id')))
    expect(ids).toEqual(expect.arrayContaining(boxed.map((b) => b.item_id)))
  }
  await page.screenshot({ path: test.info().outputPath('cited-evidence.png') })
})

test('[WEB] Export report prepares source evidence; Take-off sheet downloads a cited CSV', async ({ page, request }) => {
  let answer
  if (production) answer = await savedAnswer(page, request)
  else {
    await chatFor(page, await chooseDocument(request, 'ifc'))
    answer = await ask(page, 'How many doors are there?')
  }
  const card = page.getByTestId('answer-card').filter({ hasText: answer.question }).first()
  const trigger = card.getByRole('button', { name: 'Export report', exact: true })
  await trigger.click()
  const dialog = page.getByRole('dialog', { name: 'Export site report', exact: true })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Copy as Markdown', exact: true })).toBeEnabled({ timeout: 30_000 })
  const frame = page.frameLocator('iframe[title="Site report preview"]')
  await expect(frame.locator('body')).toContainText(answer.question)
  await expect(frame.locator('body')).toContainText(/source|evidence/i)
  await expect(dialog.getByRole('button', { name: 'Print / Save PDF', exact: true })).toBeEnabled()
  await dialog.getByRole('button', { name: 'Close export report', exact: true }).click()
  await expect(trigger).toBeFocused()
  if (production) {
    await expect(card.getByTestId('takeoff-sheet')).toBeVisible()
    test.info().annotations.push({ type: 'read-only', description: 'Take-off submission not clicked on production: it creates a new message; zero production questions used.' })
    return
  }
  const before = await page.getByTestId('answer-card').count()
  await card.getByTestId('takeoff-sheet').click()
  await expect(page.getByTestId('answer-card')).toHaveCount(before + 1, { timeout: 120_000 })
  const takeoff = page.getByTestId('answer-card').last()
  await expect(takeoff.locator('table')).toBeVisible()
  await expect(takeoff.locator('table .citation-chip').first()).toBeVisible()
  const [download] = await Promise.all([page.waitForEvent('download'), takeoff.getByTestId('takeoff-csv').click()])
  expect(download.suggestedFilename()).toMatch(/\.csv$/)
  const csv = readFileSync((await download.path())!, 'utf8')
  expect(csv.replace(/^\uFEFF/, '')).toMatch(/^Item,Quantity,Unit,Source/)
  expect(csv.trim().split(/\r?\n/).length).toBeGreaterThan(1)
  await test.info().attach('takeoff.csv', { body: csv, contentType: 'text/csv' })
})

test('[3D] Visualise keeps cited item identities; rise, storeys, camera, clear, hide and undo work', async ({ page, request }) => {
  let answer
  if (production) answer = await savedAnswer(page, request)
  else {
    await chatFor(page, await chooseDocument(request, 'ifc'))
    answer = await ask(page, 'How many windows are there?')
  }
  const card = page.getByTestId('answer-card').filter({ hasText: answer.question }).first()
  await card.getByRole('button', { name: 'Visualise it', exact: true }).click()
  const viewer = page.getByRole('region', { name: '3D viewer', exact: true }).filter({ visible: true })
  await expect(viewer).toHaveAttribute('data-state', 'ready', { timeout: 90_000 })
  const ids = answer.evidence.scene.highlight_item_ids
  expect(ids.length, 'Answer has specific 3D evidence ids').toBeGreaterThan(0)
  await expect.poll(async () => (await viewerState(page)).highlights.sort()).toEqual([...ids].sort())
  const slider = viewer.getByRole('slider', { name: 'Build step', exact: true })
  await expect(slider).toBeVisible()
  await slider.fill('0')
  await expect(slider).toHaveValue('0')
  await slider.fill((await slider.getAttribute('max'))!)
  await expect(viewer.getByTestId('build-slider')).toHaveAttribute('data-phase', 'done')
  const storey = viewer.getByLabel('Storey', { exact: true })
  const options = await storey.locator('option').evaluateAll((nodes) => nodes.map((n) => (n as HTMLOptionElement).value).filter(Boolean))
  expect(options.length, 'Real model exposes storeys').toBeGreaterThan(0)
  await storey.selectOption(options[0])
  await expect(viewer).toHaveAttribute('data-active-storey', options[0])
  if (options.length > 1) {
    await viewer.getByRole('button', { name: 'Next storey', exact: true }).click()
    await expect(storey).toHaveValue(options[1])
    await viewer.getByRole('button', { name: 'Previous storey', exact: true }).click()
    await expect(storey).toHaveValue(options[0])
  }
  await storey.selectOption('')
  const cameraBefore = (await viewerState(page)).camera
  const canvas = viewer.locator('canvas'), bounds = (await canvas.boundingBox())!
  await page.mouse.move(bounds.x + bounds.width * .55, bounds.y + bounds.height * .4)
  await page.mouse.down()
  await page.mouse.move(bounds.x + bounds.width * .7, bounds.y + bounds.height * .55, { steps: 8 })
  await page.mouse.up()
  await expect.poll(async () => (await viewerState(page)).camera).not.toEqual(cameraBefore)
  if (!production) {
    // Test hook picks the real cited item through the same handler as a pointer pick; geometry is not mocked.
    await viewer.getByRole('button', { name: 'Edit', exact: true }).click()
    const picked = await canvas.evaluate((node, id) => {
      return (node as import('../src/viewer3d/Viewer3D').LinkedViewerCanvas).__viewer3d!.pick(id)
    }, ids[0])
    expect(picked).toBe(true)
    await viewer.getByRole('button', { name: 'Remove', exact: true }).click()
    await expect.poll(async () => (await viewerState(page)).commands.hidden).toContain(ids[0])
    await viewer.getByRole('button', { name: 'Clear highlights', exact: true }).click()
    await expect.poll(async () => (await viewerState(page)).highlights).toEqual([])
    expect((await viewerState(page)).commands.hidden).toContain(ids[0])
    await viewer.getByRole('button', { name: 'Undo', exact: true }).click()
    await expect.poll(async () => (await viewerState(page)).commands.hidden).not.toContain(ids[0])
  } else {
    await viewer.getByRole('button', { name: 'Clear highlights', exact: true }).click()
    await expect.poll(async () => (await viewerState(page)).highlights).toEqual([])
    test.info().annotations.push({ type: 'read-only', description: 'Hide/undo skipped on production: edits forbidden.' })
  }
  await page.screenshot({ path: test.info().outputPath('3d-controls.png') })
})

test('[WEB] Overview, Changes and Findings show live data or explicit empty states', async ({ page, request }) => {
  await page.goto('/#/overview')
  const overview = page.getByRole('region', { name: 'Workspace overview', exact: true })
  for (const name of ["This week's changes", 'Open findings', 'Latest answers']) {
    const section = overview.getByRole('region', { name, exact: true })
    await expect(section).toHaveAttribute('aria-busy', 'false', { timeout: 30_000 })
    await expect(section.getByRole('alert')).toHaveCount(0)
    expect((await section.innerText()).trim().length).toBeGreaterThan(name.length)
  }
  await expect(overview.getByRole('region', { name: 'Start a question' }).getByRole('button')).toHaveCount(4)
  const changes = await request.get('/api/changes')
  expect(changes.ok()).toBe(true)
  const feed = (await changes.json()).changes
  await page.goto('/#/changes')
  const screen = page.getByRole('region', { name: 'Changes', exact: true })
  await expect(screen).toBeVisible()
  await expect(screen.getByRole('alert')).toHaveCount(0)
  if (feed.length) {
    await expect(screen.locator('.change-row').first()).toBeVisible()
    await screen.locator('.change-row').first().click()
    await expect(screen.locator('.comparison-header, .data-empty, .revision-summary').first()).toBeVisible({ timeout: 30_000 })
  } else await expect(screen).toContainText(/no changes/i)
  await page.goto('/#/findings')
  const findings = page.getByRole('region', { name: 'Findings', exact: true })
  const picker = findings.getByLabel('Drawing', { exact: true })
  await expect(picker).toBeEnabled()
  await expect(findings.getByText('Loading findings…', { exact: true })).toHaveCount(0, { timeout: 30_000 })
  await expect(findings.getByRole('alert')).toHaveCount(0)
  const rows = findings.locator('[data-finding-id]')
  if (await rows.count()) {
    await expect(rows.first().locator('blockquote').first()).not.toBeEmpty()
  } else await expect(findings).toContainText('No saved findings. Run checks to inspect this drawing.')
})

test('[WEB] Phone 390x844 keeps every screen within the viewport and the composer usable', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  for (const route of ['overview', 'data', 'changes', 'findings', 'chat']) {
    await page.goto(`/#/${route}`)
    await expect(page.getByRole('navigation', { name: 'Mobile navigation' })).toBeVisible()
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth), { message: `${route} must not scroll horizontally` }).toBeLessThanOrEqual(1)
  }
  const composer = page.getByRole('combobox', { name: 'Ask about your drawings' })
  await expect(composer).toBeEnabled()
  await composer.fill('How many doors are there?')
  await expect(composer).toHaveValue('How many doors are there?')
  const send = page.getByRole('button', { name: 'Send question', exact: true })
  await expect(send).toBeEnabled()
  const bounds = (await send.boundingBox())!
  expect(bounds.x).toBeGreaterThanOrEqual(0)
  expect(bounds.x + bounds.width).toBeLessThanOrEqual(390)
  expect(bounds.y + bounds.height).toBeLessThanOrEqual(844)
  await send.click({ trial: true })
  await page.screenshot({ path: test.info().outputPath('phone-composer.png') })
})
