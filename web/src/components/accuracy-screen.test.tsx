// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AccuracyScreen, loadBenchWithFallback } from './accuracy-screen'
import { DashboardApi } from '../lib/dashboard'
import recorded from './accuracy-screen.results.json'

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

describe('recorded accuracy fallback', () => {
  it.each(['missing', 'unreachable', 'malformed'])('loads real recorded metrics when the live result is %s', async (failure) => {
    const transport = vi.fn<typeof fetch>().mockImplementation(async () => {
      if (failure === 'unreachable') throw new TypeError('Failed to fetch')
      return failure === 'malformed' ? Response.json({}) : Response.json({ status: 'no_bench' }, { status: 404 })
    })
    const result = await loadBenchWithFallback(undefined, undefined, new DashboardApi(transport))
    expect(result?.data).toEqual(recorded)
    expect(result?.recorded).toBe(true)
    expect(result?.data.cells?.['ALL x ALL']).toMatchObject(recorded.cells['ALL x ALL'])
    expect(await loadBenchWithFallback('different-run', undefined, new DashboardApi(async () => Response.json({ status: 'no_bench' }, { status: 404 })))).toBeNull()
  })

  it('preserves live runs and cancellation without substituting another tag', async () => {
    const latest = { file: 'latest.json', data: { tag: 'latest', cells: {} } }
    expect(await loadBenchWithFallback(undefined, undefined, new DashboardApi(async () => Response.json(latest)))).toEqual(latest)
    const controller = new AbortController()
    controller.abort()
    await expect(loadBenchWithFallback(undefined, controller.signal, new DashboardApi(async () => { throw controller.signal.reason }))).rejects.toMatchObject({ name: 'AbortError' })
  })

  it('shows the recorded run and metrics on the page instead of No bench runs after a 404', async () => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({ status: 'no_bench' }, { status: 404 })))
    const host = document.createElement('div')
    document.body.append(host)
    const root = createRoot(host)
    try {
      await act(async () => { root.render(<AccuracyScreen />) })
      const total = recorded.cells['ALL x ALL']
      expect(host.querySelector('[aria-label="Bench run"]')?.textContent).toContain(recorded.tag)
      expect(host.querySelector('[data-testid="bench-accuracy"]')?.textContent).toBe(`${(total.accuracy * 100).toFixed(2)}%`)
      expect(host.querySelector('[data-testid="bench-correct"]')?.textContent).toBe(`${total.correct} / ${total.n - total.unscored}`)
      expect(host.querySelector('[data-testid="bench-abstentions"]')?.textContent).toBe(String(total.abstained))
      expect(host.textContent).toContain('Latest bundled recorded run')
      expect(host.textContent).not.toContain('No bench run')
    } finally { await act(async () => root.unmount()); host.remove() }
  })
})
