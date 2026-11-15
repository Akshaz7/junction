import { useEffect, useState } from 'react'
import type { KgGraph } from '../lib/kg'
import { projectsApi } from '../lib/projects-api'
import { fetchSnapshot, readCachedGraph, sameGraph, writeCachedGraph } from '../lib/graph-cache'

export const GRAPH_RETRY_MS = 3000
const MAX_TRIES = 20

/**
 * The cluster graph, stale-while-revalidate: the last good copy in localStorage (else the bundled snapshot) is shown at once,
 * the live request runs alongside and replaces it on a 200. A 202 (still being built) is asked for again and never replaces
 * a good copy already on screen.
 */
export function useProjectGraph(projectId: string, docCount: number) {
  const [state, setState] = useState<{ graph?: KgGraph; error: string; pending: boolean }>({ error: '', pending: false })
  const [key, setKey] = useState(0)
  useEffect(() => {
    if (!docCount) { setState({ error: '', pending: false }); return }
    let live = true; let timer: ReturnType<typeof setTimeout> | undefined; let tries = 0; let gotLive = false
    const aborter = new AbortController()
    const cached = readCachedGraph(projectId)
    setState({ graph: cached ?? undefined, error: '', pending: true })
    if (!cached) void fetchSnapshot(projectId, aborter.signal).then((snap) => {
      if (live && snap && !gotLive) setState((prev) => prev.graph && !prev.graph.partial ? prev : { ...prev, graph: snap })
    })
    const load = () => projectsApi.graph(projectId, { depth: 'cluster' }).then((graph) => {
      if (!live) return
      if (graph.partial) {
        // Keep a good copy on screen; with nothing to show, the partial one is the best there is.
        setState((prev) => ({ graph: prev.graph && !prev.graph.partial ? prev.graph : graph, error: '', pending: true }))
        if (++tries < MAX_TRIES) timer = setTimeout(load, GRAPH_RETRY_MS); else setState((prev) => ({ ...prev, pending: false }))
        return
      }
      gotLive = true
      writeCachedGraph(projectId, graph)
      setState((prev) => ({ graph: prev.graph && !prev.graph.partial && sameGraph(prev.graph, graph) ? prev.graph : graph, error: '', pending: false }))
    }).catch((error: unknown) => {
      if (!live) return
      // A failed refresh must not wipe a graph that is already showing.
      setState((prev) => prev.graph ? { ...prev, pending: false } : { error: error instanceof Error ? error.message : 'The graph could not be loaded.', pending: false })
    })
    void load()
    return () => { live = false; aborter.abort(); if (timer) clearTimeout(timer) }
  }, [projectId, docCount, key])
  const [slow, setSlow] = useState(false)
  useEffect(() => {
    setSlow(false)
    if (state.graph || state.error || !docCount) return
    const timer = setTimeout(() => setSlow(true), 8_000)
    return () => clearTimeout(timer)
  }, [projectId, docCount, key, state.graph, state.error])
  return { ...state, slow, retry: () => setKey((value) => value + 1) }
}
