import type { KgGraph } from './kg'
import type { Project } from './projects-api'

const KEY = (projectId: string) => `stoa-graph-cache:${projectId}`

/** The last good (HTTP 200) cluster graph this browser saw for the project. Never throws. */
export function readCachedGraph(projectId: string): KgGraph | null {
  try {
    const raw = localStorage.getItem(KEY(projectId))
    const graph = raw ? JSON.parse(raw) as KgGraph : null
    return graph && Array.isArray(graph.nodes) && Array.isArray(graph.edges) && !graph.partial ? graph : null
  } catch { return null }
}

export function writeCachedGraph(projectId: string, graph: KgGraph): void {
  try { localStorage.setItem(KEY(projectId), JSON.stringify(graph)) } catch { /* private mode or quota: the page works without it */ }
}

/** The graph bundled with the web app (public/graph-snapshots/<project_id>.json), or null when there is none. */
export async function fetchSnapshot(projectId: string, signal?: AbortSignal): Promise<KgGraph | null> {
  try {
    const response = await fetch(`/graph-snapshots/${encodeURIComponent(projectId)}.json`, { signal })
    if (!response.ok) return null
    const graph = await response.json() as KgGraph
    return Array.isArray(graph?.nodes) && Array.isArray(graph?.edges) && graph.nodes.length ? { ...graph, partial: false } : null
  } catch { return null }
}

/** True when two graphs are the same build, so swapping one for the other would only redraw the same picture. */
export function sameGraph(a: KgGraph, b: KgGraph): boolean {
  return a.version === b.version && a.built_at === b.built_at && a.nodes.length === b.nodes.length && a.edges.length === b.edges.length
}

/* The project record (name, files) is needed before the Graph tab can draw anything, so it gets the same treatment. */
const PKEY = (projectId: string) => `stoa-project-cache:${projectId}`

export function readCachedProject(projectId: string): Project | null {
  try {
    const raw = localStorage.getItem(PKEY(projectId))
    const project = raw ? JSON.parse(raw) as Project : null
    return project && project.id === projectId && Array.isArray(project.docs) ? project : null
  } catch { return null }
}

export function writeCachedProject(projectId: string, project: Project): void {
  try { localStorage.setItem(PKEY(projectId), JSON.stringify(project)) } catch { /* optional */ }
}

export async function fetchProjectSnapshot(projectId: string, signal?: AbortSignal): Promise<Project | null> {
  try {
    const response = await fetch(`/graph-snapshots/${encodeURIComponent(projectId)}.project.json`, { signal })
    if (!response.ok) return null
    const project = await response.json() as Project
    return project?.id === projectId && Array.isArray(project.docs) ? project : null
  } catch { return null }
}
