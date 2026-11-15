// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { GRAPH_RETRY_MS, useProjectGraph } from './use-project-graph'
import { projectsApi } from '../lib/projects-api'
import type { KgGraph } from '../lib/kg'

const mk = (label: string, extra: Partial<KgGraph> = {}): KgGraph => ({
  project_id: 'p1', version: 1, built_at: label, stats: { nodes: 1, edges: 0 } as KgGraph['stats'],
  nodes: [{ id: 'n', kind: 'room', label } as KgGraph['nodes'][number]], edges: [], ...extra,
})
let host: HTMLDivElement
let root: Root
function Probe() {
  const { graph, pending, error } = useProjectGraph('p1', 2)
  return <p>{`${graph?.nodes[0]?.label ?? 'none'}|${graph?.partial ? 'partial' : 'full'}|${pending ? 'pending' : 'idle'}|${error}`}</p>
}
const text = () => host.textContent
const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve() })
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.useFakeTimers()
  const store = new Map<string, string>()
  vi.stubGlobal('localStorage', { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => { store.set(k, v) }, removeItem: (k: string) => { store.delete(k) }, clear: () => store.clear() })
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(mk('snapshot')), { status: 200 })))
})
afterEach(async () => {
  await act(async () => root.unmount()); host.remove()
  vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks()
})

describe('useProjectGraph', () => {
  it('shows the snapshot first, then the live graph replaces it and is saved', async () => {
    let resolve!: (g: KgGraph) => void
    vi.spyOn(projectsApi, 'graph').mockReturnValue(new Promise((r) => { resolve = r }))
    await act(async () => root.render(<Probe />)); await flush()
    expect(text()).toBe('snapshot|full|pending|')
    await act(async () => resolve(mk('live'))); await flush()
    expect(text()).toBe('live|full|idle|')
    expect(JSON.parse(localStorage.getItem('stoa-graph-cache:p1') ?? '{}').nodes[0].label).toBe('live')
  })

  it('prefers the localStorage copy over the snapshot', async () => {
    localStorage.setItem('stoa-graph-cache:p1', JSON.stringify(mk('cached')))
    vi.spyOn(projectsApi, 'graph').mockReturnValue(new Promise(() => {}))
    await act(async () => root.render(<Probe />)); await flush()
    expect(text()).toBe('cached|full|pending|')
    expect(fetch).not.toHaveBeenCalled()
  })

  it('retries on 202 without replacing the shown graph, then swaps in the 200', async () => {
    const spy = vi.spyOn(projectsApi, 'graph')
      .mockResolvedValueOnce(mk('building', { partial: true }))
      .mockResolvedValueOnce(mk('live'))
    await act(async () => root.render(<Probe />)); await flush()
    expect(text()).toBe('snapshot|full|pending|')
    expect(localStorage.getItem('stoa-graph-cache:p1')).toBeNull()
    await act(async () => { await vi.advanceTimersByTimeAsync(GRAPH_RETRY_MS + 10) }); await flush()
    expect(spy).toHaveBeenCalledTimes(2)
    expect(text()).toBe('live|full|idle|')
  })

  it('with no snapshot, falls back to the skeleton until live arrives', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('<html></html>', { status: 200 })))
    vi.spyOn(projectsApi, 'graph').mockReturnValue(new Promise(() => {}))
    await act(async () => root.render(<Probe />)); await flush()
    expect(text()).toBe('none|full|pending|')
  })
})
