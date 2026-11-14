import { expect, test, type Page } from '@playwright/test'
import type { BenchResult, BenchRun, CostsResult } from '../src/lib/dashboard'

// Expected values come from independent real API requests, never browser mocks.
const percent = (value: number | null | undefined) => typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : 'not scored'
const usd = (value: number | null | undefined) => typeof value === 'number' && Number.isFinite(value) ? `$${value.toFixed(Math.abs(value) < 0.01 ? 6 : 2)}` : 'Not available'

async function expectBenchTotals(page: Page, result: BenchResult) {
  const totals = result.data.cells?.['ALL x ALL']
  await expect(page.getByTestId('bench-accuracy')).toHaveText(typeof totals?.accuracy === 'number' && Number.isFinite(totals.accuracy) ? `${(totals.accuracy * 100).toFixed(2)}%` : '')
  await expect(page.getByTestId('bench-answered-accuracy')).toHaveText(percent(totals?.answered_accuracy))
  await expect(page.getByTestId('bench-cost-per-answer')).toHaveText(usd(totals?.cost_usd_per_answer))
  const scored = totals?.scored ?? (typeof totals?.n === 'number' && typeof totals.unscored === 'number' ? totals.n - totals.unscored : undefined)
  await expect(page.getByTestId('bench-scored')).toHaveText(scored === undefined ? 'Not available' : scored.toLocaleString('en-US'))
  await expect(page.getByTestId('bench-latency')).toHaveText(typeof totals?.latency_ms_mean === 'number' ? `${totals.latency_ms_mean.toLocaleString('en-US')} ms` : 'Not available')
  if (result.data.fake === true) await expect(page.locator('.accuracy-screen > .accuracy-run-notice')).toContainText('test run, fake model')
}

test('accuracy and costs match the real API, including the no-bench state', async ({ page, request }) => {
  const [benchResponse, costsResponse] = await Promise.all([request.get('/api/bench/latest'), request.get('/api/costs')])
  expect(costsResponse.ok(), 'A real backend is required; dashboard tests never mock API results').toBe(true)
  const costs = await costsResponse.json() as CostsResult
  const result = await benchResponse.json()
  await page.goto('/#/accuracy')
  await expect(page.getByRole('region', { name: 'Accuracy dashboard', exact: true })).toBeVisible()
  await expect(page.getByTestId('costs-total')).toHaveText(usd(costs.total_usd))
  for (const [provider, value] of Object.entries(costs.by_provider)) {
    const row = page.getByRole('table', { name: 'Costs by provider' }).getByRole('row').filter({ has: page.getByRole('rowheader', { name: provider, exact: true }) })
    await expect(row.getByRole('cell').nth(0)).toHaveText(value.calls.toLocaleString('en-US'))
    await expect(row.getByRole('cell').nth(1)).toHaveText(usd(value.usd))
  }
  if (benchResponse.status() === 404 && result.status === 'no_bench') {
    await expect(page.getByText('No bench run yet.', { exact: true })).toBeVisible()
    await expect(page.locator('.accuracy-empty code')).toHaveText('python -m engine.bench --set sample200 --tag <t>')
    await expect(page.getByTestId('bench-accuracy')).toHaveCount(0)
  } else {
    expect(benchResponse.ok()).toBe(true)
    await expectBenchTotals(page, result as BenchResult)
    const selected = (result as BenchResult).data.tag || (result as BenchResult).file.replace(/\.json$/, '')
    await expect(page.getByRole('combobox', { name: 'Bench run', exact: true })).toHaveValue(selected)
  }
  await expect(page.getByRole('list', { name: 'Model routes' })).toHaveText('RulesNemotronRunware')
  await expect(page.getByText('switching from the UI comes with S-09', { exact: true })).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})

test('the run picker loads the selected real run', async ({ page, request }) => {
  const response = await request.get('/api/bench')
  // The older API has no run picker endpoint. Its latest run is covered above.
  if (response.status() === 404) return
  expect(response.ok()).toBe(true)
  const body = await response.json() as { benches: BenchRun[] } | BenchRun[]
  const runs = Array.isArray(body) ? body : body.benches
  if (!runs.length) return
  const target = runs[runs.length - 1]
  const resultResponse = await request.get(`/api/bench/latest?tag=${encodeURIComponent(target.tag)}`)
  expect(resultResponse.ok()).toBe(true)
  const result = await resultResponse.json() as BenchResult
  await page.goto('/#/accuracy')
  const picker = page.getByRole('combobox', { name: 'Bench run', exact: true })
  await expect(picker.locator('option').filter({ hasText: target.tag }).first()).toBeAttached()
  if (await picker.inputValue() !== target.tag) {
    const selectedResponse = page.waitForResponse((res) => new URL(res.url()).pathname === '/api/bench/latest' && new URL(res.url()).searchParams.get('tag') === target.tag)
    await picker.selectOption(target.tag)
    expect((await selectedResponse).ok()).toBe(true)
  }
  await expectBenchTotals(page, result)
})
