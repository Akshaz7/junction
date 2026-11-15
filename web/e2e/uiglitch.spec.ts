import { test, expect, type Page } from '@playwright/test'
import { mkdirSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { graphMatchMetrics, type KgStats } from '../src/lib/kg'
import type { SavedChat } from '../src/lib/types'

// Optional read-only API proxy lets this worktree exercise production evidence
// without uploading, asking questions or changing any shared server state.
const apiOrigin = process.env.UIGLITCH_API_ORIGIN ?? 'http://localhost:8000'
const output = resolve(process.env.UIGLITCH_OUTPUT_DIR ?? '../results/final/UIGLITCH')
test.beforeEach(async ({ context }) => {
  await context.route('**/api/**', async (route) => {
    if (route.request().method() !== 'GET') return route.abort('blockedbyclient')
    const url = new URL(route.request().url())
    const response = await route.fetch({ url: `${apiOrigin}${url.pathname}${url.search}` })
    await route.fulfill({ response })
  })
  await context.routeWebSocket('**/ws*', () => {})
  mkdirSync(output, { recursive: true })
})
test.afterEach(async ({ context }) => { await context.unrouteAll({ behavior: 'wait' }) })

async function capture(page: Page, name: string) { await page.screenshot({ path: resolve(output, `${name}.png`) }) }

test('graph totals, canvas, legend and selected details fit the viewport', async ({ page, request }) => {
  test.setTimeout(60_000)
  const projects = (await (await request.get(`${apiOrigin}/api/projects`)).json()).projects as { id: string; doc_count: number }[]
  const project = [...projects].sort((a, b) => b.doc_count - a.doc_count)[0]
  expect(project?.doc_count).toBeGreaterThan(0)
  const stats = await (await request.get(`${apiOrigin}/api/projects/${project.id}/graph/stats`)).json() as KgStats
  const metrics = graphMatchMetrics(stats)
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto(`/#/projects?id=${encodeURIComponent(project.id)}&tab=graph`)
  const graph = page.getByTestId('graph-tab')
  await expect(graph).toBeVisible()
  for (const [label, metric] of [['Linked across files', metrics.linked], ['Values agree', metrics.agree]] as const) {
    const tile = graph.locator('.overview-stat').filter({ has: page.getByText(label, { exact: true }) })
    await expect(tile.locator('strong')).toHaveText(metric.value)
    await expect(tile).toHaveAttribute('title', metric.hint)
  }
  const measurements = []
  for (const height of [900, 720]) {
    await page.setViewportSize({ width: 1440, height })
    await expect.poll(async () => page.locator('.pj-screen').evaluate((node) => node.scrollHeight - node.clientHeight)).toBeLessThanOrEqual(1)
    const canvas = await graph.locator('.kg-graph').boundingBox()
    const footer = await graph.locator('.kg-foot').boundingBox()
    expect(canvas!.height).toBeGreaterThan(50)
    expect(footer!.y + footer!.height).toBeLessThanOrEqual(height)
    await capture(page, `graph-${height}`)
    measurements.push({ height, canvas, footer })
  }
  await page.setViewportSize({ width: 1440, height: 900 })
  await graph.getByRole('searchbox', { name: 'Search the graph' }).fill('room')
  const hit = graph.getByRole('option').first().getByRole('button')
  await expect(hit).toBeVisible()
  await hit.click()
  const details = page.getByRole('complementary', { name: 'Item details', exact: true })
  await expect(details).toBeVisible()
  await expect.poll(async () => details.evaluate((node) => node.getBoundingClientRect().bottom)).toBeLessThan(900)
  await expect.poll(async () => page.locator('.pj-screen').evaluate((node) => node.scrollHeight - node.clientHeight)).toBeLessThanOrEqual(1)
  await capture(page, 'graph-details')
  writeFileSync(resolve(output, 'graph-validation.json'), JSON.stringify({ projectId: project.id, metrics, measurements }, null, 2) + '\n')
})

test('saved answer cost survives drawing and calculation opening across real files', async ({ page, request }) => {
  test.setTimeout(90_000)
  // IDs are evidence selected for this run, supplied by the caller, never app logic.
  const ids = (process.env.UIGLITCH_CHAT_IDS ?? '').split(',').filter(Boolean)
  test.skip(!ids.length, 'Supply UIGLITCH_CHAT_IDS with existing chats; this test never creates questions.')
  await page.setViewportSize({ width: 1440, height: 900 })
  const reports = []
  for (const [index, id] of ids.entries()) {
    const response = await request.get(`${apiOrigin}/api/chats/${encodeURIComponent(id)}`)
    expect(response.ok()).toBe(true)
    const chat = await response.json() as SavedChat
    const answers = chat.messages.flatMap((message) => message.answer ? [message.answer] : [])
    const answer = answers.find((entry) => entry.citations.length && !entry.answer.abstained)
    expect(answer, `Chat ${id} must contain a cited answer`).toBeTruthy()
    await page.goto(`/#/chat?chat=${encodeURIComponent(id)}`)
    const card = page.getByTestId('answer-card').nth(answers.indexOf(answer!))
    const chip = card.getByTestId('answer-cost')
    await expect(chip).toBeVisible()
    const before = await chip.innerText()
    const expected = answer!.cost.usd_total > 0 && answer!.cost.usd_total < 0.0001 ? '< $0.0001' : `$${answer!.cost.usd_total.toFixed(4)}`
    expect(before).toBe(expected)
    const calc = card.getByRole('button', { name: 'Show calculation', exact: true })
    if (await calc.count()) await calc.click()
    else await card.getByRole('button', { name: `Open citation ${answer!.citations[0].n}`, exact: true }).first().click()
    await expect(page.getByRole('region', { name: 'Drawing viewer', exact: true })).toBeVisible()
    await expect(chip).toHaveText(expected)
    await capture(page, `cost-file-${index + 1}`)
    reports.push({ chatId: id, answerId: answer!.answer_id, docIds: answer!.doc_ids, usdTotal: answer!.cost.usd_total, before, after: await chip.innerText() })
  }
  expect(new Set(reports.flatMap((row) => row.docIds)).size).toBeGreaterThanOrEqual(3)
  writeFileSync(resolve(output, 'cost-validation.json'), JSON.stringify(reports, null, 2) + '\n')
})
