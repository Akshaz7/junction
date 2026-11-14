import { expect, test, type Locator, type Page, type TestInfo } from '@playwright/test'
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import type ManifestShape from './fidelity-masks.json'
import { compareFrames, MAX_REGION_CANVAS_PERCENT, MAX_UNMASKED_MISMATCH_PERCENT, MAX_PHONE_UNMASKED_MISMATCH_PERCENT, type Mask } from './fidelity-diff'
import { fidelityAnswer, fidelityComparison, fidelityDocs, fidelityDrawing, fidelityFeed, fidelityQuestion } from './fidelity-fixtures'
import { phaseResults, savePhaseResult } from './fidelity-report'

const manifest = JSON.parse(readFileSync(new URL('./fidelity-masks.json', import.meta.url), 'utf8')) as typeof ManifestShape
const output = resolve(import.meta.dirname, '../../results/fidelity')
const references = resolve(import.meta.dirname, '../../refs/stoa-hero')
type Phase = typeof manifest.phases[number]
function resultDirectory(testInfo: TestInfo) { return resolve(testInfo.project.outputDir, 'fidelity-results') }
function saveReport(testInfo: TestInfo, finished = false) {
  const results = phaseResults(resultDirectory(testInfo), manifest.phases)
  const complete = results.length === manifest.phases.length
  mkdirSync(resolve(output, 'diffs'), { recursive: true })
  const failed = results.filter((phase) => phase.status === 'fail' || phase.status === 'error')
  writeFileSync(resolve(output, 'report.json'), JSON.stringify({
    complete, generated_at: new Date().toISOString(), reference: 'refs/stoa-hero',
    coordinate_space: 'CSS pixels; both PNGs are compared at native 2x resolution',
    pixelmatch: { threshold: .1, includeAA: false },
    acceptance: { max_region_canvas_percent: MAX_REGION_CANVAS_PERCENT, max_unmasked_mismatch_percent: MAX_UNMASKED_MISMATCH_PERCENT,
      max_phone_unmasked_mismatch_percent: MAX_PHONE_UNMASKED_MISMATCH_PERCENT,
      note: 'Every diff region remains in unmasked_diff_regions. Only regions above the permitted canvas percentage are unexplained; the total unmasked percentage must also pass.' },
    reference_selection: 'The _phase PNG records a transition boundary, often the previous screen. Each stable capture uses the final available PNG before the next phase; both names are recorded.',
    total_phases: manifest.phases.length, measured_phases: results.filter((phase) => ['pass', 'fail'].includes(phase.status)).length,
    not_applicable: results.filter((phase) => phase.status === 'not_applicable').length,
    unexplained_regions: results.reduce((sum, phase) => sum + (Array.isArray(phase.unexplained_regions) ? phase.unexplained_regions.length : 0), 0),
    errors: results.filter((phase) => phase.status === 'error').length,
    status: !complete && !finished ? 'running' : failed.length || !complete ? 'fail' : 'pass', phases: results,
  }, null, 2) + '\n')
}

async function settled(page: Page) {
  await page.evaluate(async () => {
    await document.fonts.ready
    await Promise.all(Array.from(document.images).filter((image) => image.getBoundingClientRect().width > 0).map((image) => image.decode().catch(() => {})))
    await new Promise<void>((done) => requestAnimationFrame(() => requestAnimationFrame(() => done())))
  })
}

// Transforming a sheet makes its bounding box extend far beyond its viewport.
// Content masks must respect clipping and the phone's overlaid readings sheet.
async function visibleMasks(locator: Locator, textOnly: boolean, reason: string): Promise<Mask[]> {
  if (!await locator.isVisible()) return []
  const rects = await locator.evaluate((node, onlyText) => {
    let left = 0, top = 0, right = innerWidth, bottom = innerHeight
    for (let parent = node.parentElement; parent; parent = parent.parentElement) {
      const style = getComputedStyle(parent), box = parent.getBoundingClientRect()
      if (/(hidden|clip|auto|scroll)/.test(style.overflowX)) { left = Math.max(left, box.left); right = Math.min(right, box.right) }
      if (/(hidden|clip|auto|scroll)/.test(style.overflowY)) { top = Math.max(top, box.top); bottom = Math.min(bottom, box.bottom) }
    }
    if (node.matches('.comparison-sheet')) {
      const summary = document.querySelector('.phone-comparison-summary')
      if (summary && getComputedStyle(summary).display !== 'none') bottom = Math.min(bottom, summary.getBoundingClientRect().top)
      const labels = document.querySelector('.wipe-labels')
      if (labels) top = Math.max(top, labels.getBoundingClientRect().bottom)
    }
    const clip = (box: DOMRect) => ({ x: Math.max(left, box.left), y: Math.max(top, box.top),
      width: Math.max(0, Math.min(right, box.right) - Math.max(left, box.left)),
      height: Math.max(0, Math.min(bottom, box.bottom) - Math.max(top, box.top)) })
    if (!onlyText) return [clip(node.getBoundingClientRect())]
    const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT)
    const boxes: ReturnType<typeof clip>[] = []
    while (walker.nextNode()) {
      const text = walker.currentNode
      if (!text.textContent?.trim() || text.parentElement?.closest('button, svg')) continue
      const range = document.createRange(); range.selectNodeContents(text)
      boxes.push(...Array.from(range.getClientRects()).map(clip))
    }
    return boxes
  }, textOnly)
  return rects.filter((box) => box.width > 0 && box.height > 0).map((box) => ({ ...box, reason }))
}

function checkSettledReferences() {
  for (const device of ['desktop', 'phone']) {
    const frames = readdirSync(resolve(references, `${device}-frames`)).filter((file) => /_t\d+ms(?:_phase)?\.png$/.test(file))
      .map((file) => ({ file, time: Number(file.match(/_t(\d+)ms/)![1]) })).sort((a, b) => a.time - b.time)
    const phases = manifest.phases.filter((phase) => phase.device === device)
    for (let i = 0; i < phases.length; i++) {
      const phase = phases[i]
      if (phase.status === 'not_applicable') continue
      const next = phases[i + 1]
      if (!next) throw new Error(`Missing next boundary for ${phase.id}`)
      const end = Number(next.reference_boundary.match(/_t(\d+)ms/)![1])
      const last = frames.filter((frame) => frame.time < end).at(-1)
      expect(phase.reference_settled, `Settled reference for ${phase.id}`).toBe(`${device}-frames/${last?.file}`)
    }
  }
}

async function press(page: Page, locator: Locator) {
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      await expect(locator).toBeVisible()
      // Trial clicks wait for stability and scroll into view without releasing
      // the held press used by the reference. Re-resolve after a chat refresh.
      await locator.click({ trial: true })
      const box = await locator.boundingBox()
      if (!box) throw new Error('Press target has no bounding box')
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
      await page.mouse.down()
      return
    } catch (error) {
      if (attempt || !(error instanceof Error) || !/not attached|detached|no bounding box/i.test(error.message)) throw error
    }
  }
}

async function setWipe(page: Page, value: number) {
  const slider = page.getByRole('slider', { name: 'Wipe position' })
  await slider.focus()
  await slider.press('Home')
  for (let n = 0; n < Math.floor(value / 10); n++) await slider.press('PageUp')
  for (let n = 0; n < value % 10; n++) await slider.press('ArrowRight')
  await expect(slider).toHaveValue(String(value))
  await slider.evaluate((node) => node.blur())
}

// Every phase starts in a fresh context and reaches its own state through real
// clicks. A held press is only the final action; it never gates the next test.
async function preparePhase(page: Page, phase: Phase, answerGate: Promise<void>) {
  const device = phase.device, n = phase.phase
  const thinking = n === (device === 'desktop' ? 7 : 9)
  await page.context().route('**/api/**', async (route) => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (path === '/api/docs') {
      const sources = [...new Set(fidelityDocs.map((doc) => doc.source))].map((source) => ({ source, docs: fidelityDocs.filter((doc) => doc.source === source) }))
      return route.fulfill({ json: { total: fidelityDocs.length, sources } })
    }
    const doc = fidelityDocs.find((entry) => path === `/api/docs/${entry.doc_id}`)
    if (doc) return route.fulfill({ json: doc })
    if (/\/pages\/\d+\/image$|\.thumb\.png$|^\/api\/fidelity\//.test(path)) return route.fulfill({ contentType: 'image/svg+xml', body: fidelityDrawing(path.includes('previous')) })
    if (path === '/api/chats' && request.method() === 'POST') return route.fulfill({ json: { id: 'fidelity-generated-chat' } })
    // Live reconnects refetch the persisted chat, just as the real API does.
    if (path === '/api/chats/fidelity-generated-chat' && request.method() === 'GET') {
      await answerGate
      return route.fulfill({ json: { id: 'fidelity-generated-chat', doc_id: fidelityAnswer.doc_ids[0], messages: [
        { id: 'fidelity-question', role: 'user', content: fidelityAnswer.question, answer: null },
        { id: 'fidelity-answer', role: 'assistant', content: fidelityAnswer.answer.text_md, answer: fidelityAnswer },
      ] } }).catch(() => {})
    }
    if (path.endsWith('/messages')) {
      await answerGate
      return route.fulfill({ contentType: 'text/event-stream', body: `event: answer\ndata: ${JSON.stringify(fidelityAnswer)}\n\n` }).catch(() => {})
    }
    if (path === '/api/changes') return route.fulfill({ json: { changes: fidelityFeed } })
    if (path.startsWith('/api/changes/')) return route.fulfill({ json: fidelityComparison })
    return route.fulfill({ status: 404, json: { detail: 'No such generated fidelity fixture.' } })
  })
  const navigation = () => page.getByRole('navigation', { name: device === 'desktop' ? 'Workspace navigation' : 'Mobile navigation', exact: true })
  const composer = () => page.getByRole('combobox', { name: 'Ask about your drawings' })
  const citation = () => page.locator('.answer-text').getByRole('button', { name: 'Open citation 2', exact: true })
  const file = () => page.locator('.data-open-file').first()
  const change = () => page.locator('.change-row').first()
  const wipeButton = () => page.getByRole('button', { name: 'Wipe', exact: true })
  const scene = phase.expected_state?.scene
  if (!scene) throw new Error(`Missing settled app state for ${phase.id}`)
  await page.goto(`/#/${scene}`)
  // Add the reference's native status/home safe areas without changing component geometry.
  if (device === 'phone') await page.addStyleTag({ content: ':root { --app-safe-top:44px; --app-safe-bottom:34px; }' })
  // Deliberate Stoa Pro rebrand (W-66): the rail is 104px, the reference's 64px. Compare the content
  // area at the reference geometry; the rail itself is masked below as the rebrand region.
  if (device === 'desktop') await page.addStyleTag({ content: '.app-shell { grid-template-columns: 64px minmax(0, 1fr) !important; }' })
  await expect(page.getByText('Connected workspace', { exact: true })).toBeVisible()
  let target: Locator | undefined
  if (scene === 'data') {
    await expect(file()).toBeVisible()
    if (n === 2) target = file()
    if (n >= 3) {
      await file().click()
      await expect(page.locator('aside.data-detail')).toBeVisible()
      const preview = page.locator('.data-detail .data-preview img')
      await expect.poll(() => preview.evaluate((image: HTMLImageElement) => image.complete && image.naturalWidth > 0)).toBe(true)
      if (device === 'desktop') {
        await expect(page.getByLabel('Page zoom level', { exact: true })).toHaveText('100%')
        await expect(page.locator('.data-page-plane')).toHaveCSS('transform', 'matrix(1, 0, 0, 1, 0, 0)')
      } else {
        // Phone zoom reports actual page pixels, rather than a multiple of fit.
        await expect.poll(() => preview.evaluate((image: HTMLImageElement) => {
          const canvas = image.closest('.data-page-canvas')!.getBoundingClientRect()
          const rect = image.getBoundingClientRect()
          const width = Math.min(image.naturalWidth, canvas.width - 24)
          return Math.abs(rect.width - width) < 1 && Math.abs(rect.top - canvas.top - 12) < 1
        })).toBe(true)
        const initialZoom = Number.parseFloat(await page.getByLabel('Page zoom level', { exact: true }).innerText())
        expect(initialZoom).toBeLessThanOrEqual(100)
      }
    }
    if (device === 'desktop' && n === 4) target = navigation().getByRole('link', { name: 'Chat', exact: true })
    if (device === 'phone') {
      if (n >= 4) {
        // The reference's large sheet reaches 57% actual scale. Small generated
        // sheets already open above that; do not enlarge their text 3.75 times.
        const initialZoom = Number.parseFloat(await page.getByLabel('Page zoom level', { exact: true }).innerText())
        const clicks = Math.max(0, Math.min(12, Math.floor((57 / initialZoom - 1) * 4)))
        for (let i = 0; i < clicks; i++) await page.getByRole('button', { name: 'Zoom in', exact: true }).click()
        expect(Number.parseFloat(await page.getByLabel('Page zoom level', { exact: true }).innerText())).toBeLessThanOrEqual(100)
      }
      if (n >= 3) {
        // A drawing mask must never conceal a blank or off-canvas preview.
        await expect.poll(() => page.locator('.data-detail .data-preview img').evaluate((image) => {
          const drawing = image.getBoundingClientRect()
          const canvas = image.closest('.data-page-canvas')!.getBoundingClientRect()
          return Math.min(drawing.right, canvas.right) - Math.max(drawing.left, canvas.left) > 64
            && Math.min(drawing.bottom, canvas.bottom) - Math.max(drawing.top, canvas.top) > 64
        })).toBe(true)
        await expect(page.locator('.data-detail')).toHaveCSS('background-color', 'rgb(255, 255, 255)')
        expect((await page.locator('.data-detail').boundingBox())?.y).toBe(0)
      }
      if (n === 5) target = page.getByRole('button', { name: 'Close document details', exact: true })
      if (n === 6) {
        await page.getByRole('button', { name: 'Close document details', exact: true }).click()
        await expect(page.locator('.data-detail')).toHaveCount(0)
        target = navigation().getByRole('link', { name: 'Chat', exact: true })
      }
    }
  } else if (scene === 'chat') {
    await composer().fill(fidelityQuestion)
    const sendPhase = device === 'desktop' ? 6 : 8
    if (n === sendPhase) target = page.getByRole('button', { name: 'Send question', exact: true })
    if (n > sendPhase) {
      await page.getByRole('button', { name: 'Send question', exact: true }).click()
      // A drawing question is held until a document is chosen; choose the generated one.
      await page.getByTestId('need-document').getByRole('button', { name: 'Choose a document' }).click()
      await page.getByRole('option').first().click()
      if (thinking) await expect(page.locator('.status-lines')).toBeVisible()
      else await expect(page.locator('.answer-text')).toBeVisible()
    }
    const citationPress = device === 'desktop' ? 9 : 11
    if (n === citationPress) target = citation()
    if (n > citationPress) {
      await citation().click()
      await expect(device === 'desktop' ? page.getByRole('region', { name: 'Drawing viewer' }) : page.locator('aside.document-viewer')).toBeVisible()
      if (device === 'desktop' && n === 11) target = navigation().getByRole('link', { name: 'Changes', exact: true })
      if (device === 'phone' && n === 13) target = page.getByRole('button', { name: 'Close drawing viewer', exact: true })
      if (device === 'phone' && n === 14) {
        await page.getByRole('button', { name: 'Close drawing viewer', exact: true }).click()
        await expect(page.locator('.document-viewer')).toHaveCount(0)
        target = navigation().getByRole('link', { name: 'Changes', exact: true })
      }
    }
  } else {
    await expect(change()).toBeVisible()
    const rowPress = device === 'desktop' ? 13 : 16
    if (n === rowPress) target = change()
    if (n > rowPress) {
      await change().click()
      await expect(page.locator('.comparison-sheet img').first()).toBeVisible()
      if (device === 'phone' && n >= 18) for (let i = 0; i < 8; i++) await page.getByRole('button', { name: 'Zoom in comparison', exact: true }).click()
      const wipePress = device === 'desktop' ? 15 : 19
      if (n >= wipePress) await wipeButton().click()
      if (n === wipePress) target = wipeButton()
      if (n > wipePress) await setWipe(page, device === 'desktop' ? (n === 16 ? 76 : 34) : (n === 20 ? 78 : 30))
    }
  }
  if (target) await press(page, target)
}

async function screenshotPhase(page: Page, phase: Phase, testInfo: TestInfo) {
  // Remove rail hover/focus tooltips while keeping any final press held. No later
  // state depends on mouseup: each phase has its own context and click setup.
  await page.locator('.rail a:focus').evaluateAll((nodes) => nodes.forEach((node) => (node as HTMLElement).blur()))
  await page.mouse.move(1, 1)
  // Moving with a held press drags a text selection across the page; the reference has none.
  await page.evaluate(() => window.getSelection()?.removeAllRanges())
  await settled(page)
  const state = phase.expected_state
  if (!state) throw new Error(`Missing settled app state for ${phase.id}`)
  await expect(page).toHaveURL(new RegExp(`#/${state.scene}${state.scene === 'chat' ? '(?:\\?chat=[^&]+)?' : ''}$`))
  await expect(page.locator('.data-detail:visible')).toHaveCount(state.panel === 'document' ? 1 : 0)
  await expect(page.locator('.document-viewer:visible')).toHaveCount(state.panel === 'citation' ? 1 : 0)
  await expect(page.locator('.comparison-box:visible')).toHaveCount(state.panel === 'comparison' ? 1 : 0)
  if ('chat' in state) {
    if (state.chat === 'draft') await expect(page.getByRole('combobox', { name: 'Ask about your drawings' })).toHaveValue(fidelityQuestion)
    if (state.chat === 'thinking') await expect(page.locator('.pending-exchange')).toBeVisible()
    if (state.chat === 'answer') await expect(page.locator('.answer-text')).toBeVisible()
  }
  if ('mode' in state && state.mode) await expect(page.getByRole('button', { name: state.mode, exact: true })).toHaveAttribute('aria-pressed', 'true')
  const masks: Mask[] = [...phase.masks]
  if (phase.device === 'desktop') masks.push({ x: 0, y: 0, width: 72, height: 800, reason: 'Deliberate Stoa Pro rebrand (W-66): the rail carries our logo and PRO mark; the content area is compared at the reference 64px rail geometry.' })
  if (phase.device === 'desktop') masks.push(
    { x: 72, y: 8, width: 256, height: 56, reason: 'Deliberate Stoa Pro rebrand (W-63): the mark in the top bar.' },
    { x: 1040, y: 8, width: 208, height: 56, reason: 'Our additions to the header (W-39 Pair a phone, share/export), not in the reference.' })
  if (phase.device === 'phone') masks.push({ x: 48, y: 48, width: 176, height: 32, reason: 'Deliberate Stoa Pro rebrand (W-71): the mark top left.' }, { x: 352, y: 48, width: 32, height: 32, reason: 'Deliberate Stoa Pro rebrand (W-69): the mark top right.' })
  for (const item of phase.selectors || []) {
    for (const locator of await page.locator(item.selector).all()) {
      masks.push(...await visibleMasks(locator, item.text_only, item.reason))
    }
  }
  // Generated prose is masked, but its inline controls still need the reference geometry.
  const chip = page.locator('.answer-text .citation-chip').first()
  if (await chip.isVisible()) {
    await expect(chip).toHaveCSS('border-radius', '6px')
    await expect(chip).toHaveCSS('width', '20px')
    await expect(chip).toHaveCSS('height', '20px')
  }
  const actual = await page.screenshot({ animations: 'disabled', caret: 'hide', scale: 'device' })
  writeFileSync(resolve(output, `${phase.id}.png`), actual)
  const { diff, ...measurement } = compareFrames(actual, readFileSync(resolve(references, phase.reference_settled)), masks, 2, phase.device)
  const diffPath = resolve(output, 'diffs', `${phase.id}.png`)
  writeFileSync(diffPath, diff)
  savePhaseResult(resultDirectory(testInfo), { id: phase.id, device: phase.device, phase: phase.phase,
    reference_boundary: phase.reference_boundary, reference_settled: phase.reference_settled, reference_compared: phase.reference_settled,
    expected_state: state, actual_url: page.url(), actual: `${phase.id}.png`, diff: `diffs/${phase.id}.png`, masks, ...measurement })
  saveReport(testInfo)
  await testInfo.attach(`${phase.id}-diff`, { path: diffPath, contentType: 'image/png' })
  expect(measurement.status, `${phase.id}: ${measurement.mismatch_percent.toFixed(3)}% mismatch, ${measurement.unexplained_regions.length} unexplained regions. See results/fidelity/report.json and diffs/.`).toBe('pass')
}

test.describe('Stoa reference fidelity', () => {
  test.beforeAll(({}, testInfo) => { checkSettledReferences(); saveReport(testInfo) })
  for (const device of ['desktop', 'phone'] as const) {
    test.describe(device, () => {
      test.use({ viewport: device === 'desktop' ? { width: 1280, height: 800 } : { width: 390, height: 844 },
        deviceScaleFactor: 2, reducedMotion: 'reduce', locale: 'en-GB', timezoneId: 'UTC' })
      for (const phase of manifest.phases.filter((entry) => entry.device === device)) {
        test(phase.id, async ({ page }, testInfo) => {
          test.setTimeout(60_000)
          if (phase.status === 'not_applicable') {
            savePhaseResult(resultDirectory(testInfo), { id: phase.id, device, phase: phase.phase, status: 'not_applicable', reason: phase.reason })
            saveReport(testInfo)
            test.skip(true, phase.reason)
          }
          let releaseAnswer = () => {}
          const answerGate = new Promise<void>((done) => { releaseAnswer = done })
          if (phase.phase !== (device === 'desktop' ? 7 : 9)) releaseAnswer()
          try {
            await preparePhase(page, phase, answerGate)
            await screenshotPhase(page, phase, testInfo)
          } catch (error) {
            // Keep a measured failure; only preparation/capture failures become errors.
            if (!phaseResults(resultDirectory(testInfo), [phase]).length) {
              savePhaseResult(resultDirectory(testInfo), { id: phase.id, device, phase: phase.phase, status: 'error',
                reason: error instanceof Error ? error.message : String(error) })
            }
            throw error
          } finally {
            releaseAnswer()
            saveReport(testInfo)
          }
        })
      }
    })
  }
  test.afterAll(({}, testInfo) => { saveReport(testInfo, true) })
})
