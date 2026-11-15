import { afterEach, describe, expect, it, vi } from 'vitest'
import { GRAPH_TIMEOUT_MS, projectsApi } from './projects-api'

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

describe('projectsApi.graph', () => {
  it('ends a request that never answers with a message instead of waiting forever', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', (_input: unknown, init?: RequestInit) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(init.signal?.reason ?? new DOMException('Aborted', 'AbortError')))
    }))
    const result = projectsApi.graph('p1', { depth: 'cluster' }).then(() => 'ok', (error: Error) => error.message)
    await vi.advanceTimersByTimeAsync(GRAPH_TIMEOUT_MS + 10)
    expect(await result).toMatch(/taking too long/i)
  })
})
