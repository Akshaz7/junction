import { describe, expect, it, vi } from 'vitest'
import {
  accuracyMatrix, comparisonRuns, DashboardApi, formatDelta, formatLatency, formatNumber,
  formatPercent, formatUsd, questionsScored, runLabel, runTag, type BenchResult, type BenchRun,
} from './dashboard'

const result: BenchResult = {
  file: 'baseline.json',
  data: { tag: 'baseline', set: 'sample200', fake: false, cells: {
    'ALL x ALL': { n: 10, unscored: 2, accuracy: 0.5, answered_accuracy: 0.8, cost_usd_per_answer: 0.000012, latency_ms_mean: 12 },
    'raster x count': { n: 8, unscored: 0, accuracy: 0.5 },
    'raster x text': { n: 2, unscored: 2, accuracy: null },
  } },
}

describe('dashboard values', () => {
  it('distinguishes zero, unscored and missing values without fabricating numbers', () => {
    expect(formatPercent(0)).toBe('0.0%')
    expect(formatPercent(0.974)).toBe('97.4%')
    for (const value of [null, undefined, NaN, Infinity, '0.9']) expect(formatPercent(value)).toBe('not scored')
    expect(formatUsd(0)).toBe('$0.000000')
    expect(formatUsd(0.00001234)).toBe('$0.000012')
    expect(formatUsd(0.01)).toBe('$0.01')
    expect(formatUsd(2.135)).toBe('$2.13')
    expect(formatUsd(undefined)).toBe('Not available')
    expect(formatLatency(0)).toBe('0 ms')
    expect(formatLatency(null)).toBe('Not available')
    expect(formatNumber(1000)).toBe('1,000')
  })

  it('uses scored when present or subtracts unscored from the cell count, never the run total', () => {
    expect(questionsScored(result.data.cells!['ALL x ALL'])).toBe(8)
    expect(questionsScored({ scored: 0, n: 10, unscored: 0 })).toBe(0)
    expect(questionsScored({ n: 2, unscored: 2 })).toBe(0)
    expect(questionsScored({ n: 8 })).toBeUndefined()
    expect(questionsScored()).toBeUndefined()
  })

  it('forms source/type cells without double-counting ALL rows and preserves unscored cells', () => {
    const matrix = accuracyMatrix({ ...result.data.cells, 'ALL x count': { accuracy: 1 }, 'raster x ALL': { accuracy: 1 }, 'ifc x count': { accuracy: 0 }, 'invalid': {} })
    expect(matrix.sources).toEqual(['ifc', 'raster'])
    expect(matrix.types).toEqual(['count', 'text'])
    expect(matrix.rows.get('raster')?.get('text')?.accuracy).toBeNull()
    expect(matrix.rows.get('ifc')?.get('count')?.accuracy).toBe(0)
    expect(matrix.rows.get('ifc')?.get('text')).toBeUndefined()
    expect(accuracyMatrix().sources).toEqual([])
  })

  it('labels fake and unknown model modes explicitly, including filename-only runs', () => {
    expect(runLabel({ tag: 'baseline', fake: true })).toBe('baseline · test run, fake model')
    expect(runLabel({ tag: 'baseline', fake: false })).toBe('baseline')
    expect(runLabel({ tag: 'legacy', fake: null })).toContain('model mode unknown')
    expect(runTag({ file: 'legacy.json', data: {} })).toBe('legacy')
  })

  it('reports signed percentage-point deltas and leaves unscored comparisons unscored', () => {
    expect(formatDelta(0.5, 0.62)).toBe('+12.0 pp')
    expect(formatDelta(0.62, 0.5)).toBe('-12.0 pp')
    expect(formatDelta(0.5, 0.5)).toBe('0.0 pp')
    expect(formatDelta(null, 0.5)).toBe('not scored')
  })
})

describe('fine-tuning comparisons', () => {
  const run = (tag: string, set = 'sample200', fake = false, mtime = 1): BenchRun => ({ tag, set, fake, mtime })
  it('matches baseline and ft/finetune tags only on the same set and fake mode', () => {
    expect(comparisonRuns([run('baseline'), run('ft-v1')], result)?.map((row) => row.tag)).toEqual(['baseline', 'ft-v1'])
    expect(comparisonRuns([run('baseline'), run('finetune-v1')], result)?.[1].tag).toBe('finetune-v1')
    expect(comparisonRuns([run('baseline'), run('fine-tuned')], result)?.[1].tag).toBe('fine-tuned')
    expect(comparisonRuns([run('baseline'), run('ft-v1', 'full')], result)).toBeNull()
    expect(comparisonRuns([run('baseline'), run('ft-v1', 'sample200', true)], result)).toBeNull()
    expect(comparisonRuns([run('baseline'), run('left-test')], result)).toBeNull()
    expect(comparisonRuns([run('baseline-ft')], result)).toBeNull()
  })

  it('prefers the selected run and the newest matching counterpart', () => {
    const pair = comparisonRuns([run('new-baseline', 'sample200', false, 4), run('baseline'), run('ft-old'), run('ft-new', 'sample200', false, 2)], result)
    expect(pair?.map((row) => row.tag)).toEqual(['baseline', 'ft-new'])
  })

  it('does not compare unknown question sets or unknown model modes', () => {
    expect(comparisonRuns([run('baseline'), run('ft')], { file: 'legacy.json', data: {} })).toBeNull()
  })
})

describe('real dashboard API', () => {
  it('accepts the server run-list envelope and a direct list, with a legacy 404 fallback', async () => {
    const rows = [{ tag: 'real', set: 'sample200', fake: false, mtime: '2026-11-14T00:00:00Z' }]
    const transport = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ benches: rows }))
      .mockResolvedValueOnce(Response.json(rows)).mockResolvedValueOnce(Response.json({ detail: 'Not Found' }, { status: 404 }))
    const api = new DashboardApi(transport)
    expect(await api.getRuns()).toEqual(rows)
    expect(await api.getRuns()).toEqual(rows)
    expect(await api.getRuns()).toEqual([])
  })

  it('loads latest or a URL-encoded tag and forwards cancellation', async () => {
    const transport = vi.fn<typeof fetch>().mockImplementation(async () => Response.json(result))
    const api = new DashboardApi(transport)
    const signal = new AbortController().signal
    expect(await api.getBench(undefined, signal)).toEqual(result)
    expect(await api.getBench('baseline / a&b', signal)).toEqual(result)
    expect(transport.mock.calls).toEqual([
      ['/api/bench/latest', { signal }], ['/api/bench/latest?tag=baseline%20%2F%20a%26b', { signal }],
    ])
  })

  it('treats only the explicit no_bench response as empty', async () => {
    const transport = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ status: 'no_bench' }, { status: 404 }))
      .mockResolvedValueOnce(Response.json({ detail: 'Not Found' }, { status: 404 }))
      .mockResolvedValueOnce(Response.json({ detail: 'Unavailable' }, { status: 503 }))
    const api = new DashboardApi(transport)
    expect(await api.getBench()).toBeNull()
    await expect(api.getBench()).rejects.toThrow('(404)')
    await expect(api.getBench()).rejects.toThrow('(503)')
  })

  it('loads real provider costs including zero spend without substituting demo values', async () => {
    const costs = { total_usd: 0, calls: 2, by_provider: { fake: { calls: 2, usd: 0 } }, by_task: {} }
    const transport = vi.fn<typeof fetch>().mockResolvedValue(Response.json(costs))
    expect(await new DashboardApi(transport).getCosts()).toEqual(costs)
    expect(transport.mock.calls[0][0]).toBe('/api/costs')
  })

  it('surfaces network, malformed data and server failures instead of showing empty or zero', async () => {
    await expect(new DashboardApi(vi.fn<typeof fetch>().mockRejectedValue(new TypeError('offline'))).getBench()).rejects.toThrow('offline')
    const malformed = new DashboardApi(vi.fn<typeof fetch>().mockResolvedValue(Response.json({})))
    await expect(malformed.getBench()).rejects.toThrow('unavailable')
    await expect(malformed.getRuns()).rejects.toThrow('unavailable')
    await expect(malformed.getCosts()).rejects.toThrow('unavailable')
    const failed = new DashboardApi(vi.fn<typeof fetch>().mockResolvedValue(new Response('Bad gateway', { status: 502 })))
    await expect(failed.getCosts()).rejects.toThrow('(502)')
    await expect(failed.getRuns()).rejects.toThrow('(502)')
  })
})
