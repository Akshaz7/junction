/** Saved design versions (3D edits kept as a new version of the same document) and picking any two versions to compare. */
import { apiFetch, workspaceApi } from './api'

export interface EditSnapshot {
  removed: string[]
  /** Metres moved from the original spot, world X/Z (east, south), as EditState.moveDelta. */
  moved: Record<string, [number, number]>
  materials: Record<string, string>
}

export interface SavedVersion {
  doc_id: string; n: number; parent: number; label: string; created: boolean
  change_id: string; compare_url: string; n_changes: number
  counts: { removed: number; added: number; moved: number; material: number }
}

/** The design as it stands in 3D: hidden items count as removed. */
export function editSnapshot(hidden: readonly string[], state: { moveDelta?: Record<string, [number, number]>; materials?: Record<string, string> }): EditSnapshot {
  return { removed: [...new Set(hidden)].sort(), moved: { ...(state.moveDelta ?? {}) }, materials: { ...(state.materials ?? {}) } }
}

export const hasEdits = (s: EditSnapshot) => s.removed.length > 0 || Object.keys(s.moved).length > 0 || Object.keys(s.materials).length > 0

/** The offline demo (VITE_USE_MOCK) answers from the local mock API, like every other workspace call. */
const demoTransport: typeof fetch = async (input, init) => {
  const { handleMockRequest } = await import('../mock/handler')
  return await handleMockRequest(new Request(new URL(String(input), 'http://localhost'), init)) ?? Response.json({ detail: 'This action is unavailable in the offline demo.' }, { status: 404 })
}

export async function saveDesignVersion(docId: string, snapshot: EditSnapshot, opts: { parent?: number; chatId?: string } = {},
  transport?: typeof fetch): Promise<SavedVersion> {
  const response = await (transport ?? (workspaceApi.isDemo ? demoTransport : apiFetch))(`/api/docs/${encodeURIComponent(docId)}/versions`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...snapshot, parent: opts.parent ?? 0, chat_id: opts.chatId }),
  })
  if (!response.ok) {
    let detail = `Could not save the version (${response.status}).`
    try { detail = (await response.json()).detail || detail } catch { /* no JSON body */ }
    throw new Error(detail)
  }
  return response.json() as Promise<SavedVersion>
}

export function savedMessage(v: SavedVersion): string {
  const c = v.counts, parts = [
    c.removed && `${c.removed} removed`, c.added && `${c.added} added back`, c.moved && `${c.moved} moved`, c.material && `${c.material} material changed`,
  ].filter(Boolean)
  return `${v.created ? 'Saved as' : 'Already saved as'} ${v.label.split(' · ')[0]}${parts.length ? ` (${parts.join(', ')})` : ''}.`
}

/** A feed entry that can be paired with any other version of its drawing. */
export interface PairableEntry {
  id: string
  summary: { index_a?: number; index_b?: number; version_a?: string | number; version_b?: string | number; pair_prefix?: string }
}
export interface VersionOption { index: number; label: string }

const labelOf = (value: string | number | undefined, index: number) => typeof value === 'number' ? `Version ${value}` : value || `Version ${index}`

/** Every version named by the entries of one drawing, oldest first. Empty when the entries cannot be paired freely
 *  (e.g. a matched upload has no version number on the server: that drawing keeps its fixed pairs). */
export function versionOptions(entries: readonly PairableEntry[]): VersionOption[] {
  const seen = new Map<number, string>()
  for (const { summary: s } of entries) {
    if (!s.pair_prefix || s.index_a == null || s.index_b == null) return []
    if (!seen.has(s.index_a)) seen.set(s.index_a, labelOf(s.version_a, s.index_a))
    if (!seen.has(s.index_b)) seen.set(s.index_b, labelOf(s.version_b, s.index_b))
  }
  return [...seen].map(([index, label]) => ({ index, label })).sort((a, b) => a.index - b.index)
}

const prefixOf = (entries: readonly PairableEntry[]) => entries.find((e) => e.summary.pair_prefix)?.summary.pair_prefix

/** Comparison id for versions a -> b: the feed entry's own id when one exists, else `<prefix><a>-<b>`. */
export function pairId(entries: readonly PairableEntry[], a: number, b: number): string | null {
  const own = entries.find((e) => e.summary.index_a === a && e.summary.index_b === b)
  if (own) return own.id
  const prefix = prefixOf(entries)
  return prefix ? `${prefix}${a}-${b}` : null
}

/** Versions a -> b named by a comparison id (a feed entry id or `<prefix><a>-<b>`), else null. */
export function pairOf(entries: readonly PairableEntry[], id: string): { a: number; b: number } | null {
  const own = entries.find((e) => e.id === id)
  if (own && own.summary.index_a != null && own.summary.index_b != null) return { a: own.summary.index_a, b: own.summary.index_b }
  const prefix = prefixOf(entries)
  const m = prefix && id.startsWith(prefix) ? /^(\d+)-(\d+)$/.exec(id.slice(prefix.length)) : null
  return m ? { a: Number(m[1]), b: Number(m[2]) } : null
}

/** True when the id belongs to these entries (one of them, or a free pair under their prefix). */
export const ownsId = (entries: readonly PairableEntry[], id: string) => !!id && (entries.some((e) => e.id === id) || pairOf(entries, id) !== null)

/** Default Compare pick when nothing is chosen: the most recently saved edited design, latest version against the original. */
export function latestEditedPair(entries: readonly (PairableEntry & { created_at?: string; summary: PairableEntry['summary'] & { edited?: boolean } })[]): string | null {
  const edited = entries.filter((e) => e.summary.edited && e.summary.pair_prefix && e.summary.index_b != null)
  const newest = edited.reduce<typeof edited[number] | null>((best, e) => !best || (Date.parse(e.created_at ?? '') || 0) >= (Date.parse(best.created_at ?? '') || 0) ? e : best, null)
  return newest ? `${newest.summary.pair_prefix}0-${newest.summary.index_b}` : null
}

export interface SnapshotChange { action: 'removed' | 'added' | 'moved' | 'material'; item_id: string; delta_m?: [number, number]; old?: string | null; new?: string | null }
const MOVE_TOL = 0.05

/** Snapshot a -> b by item id (same rules as engine/design_versions.py diff; used by the offline demo API). */
export function diffSnapshots(a: EditSnapshot, b: EditSnapshot): SnapshotChange[] {
  const ra = new Set(a.removed), rb = new Set(b.removed)
  const out: SnapshotChange[] = [
    ...[...rb].filter((id) => !ra.has(id)).sort().map((item_id) => ({ action: 'removed' as const, item_id })),
    ...[...ra].filter((id) => !rb.has(id)).sort().map((item_id) => ({ action: 'added' as const, item_id })),
  ]
  for (const id of [...new Set([...Object.keys(a.moved), ...Object.keys(b.moved)])].sort()) {
    if (rb.has(id)) continue
    const pa = a.moved[id] ?? [0, 0], pb = b.moved[id] ?? [0, 0]
    const d: [number, number] = [Math.round((pb[0] - pa[0]) * 1000) / 1000, Math.round((pb[1] - pa[1]) * 1000) / 1000]
    if (Math.abs(d[0]) >= MOVE_TOL || Math.abs(d[1]) >= MOVE_TOL) out.push({ action: 'moved', item_id: id, delta_m: d })
  }
  for (const id of [...new Set([...Object.keys(a.materials), ...Object.keys(b.materials)])].sort()) {
    if (!rb.has(id) && a.materials[id] !== b.materials[id]) out.push({ action: 'material', item_id: id, old: a.materials[id] ?? null, new: b.materials[id] ?? null })
  }
  return out
}

/** "1.0 m east, 0.5 m north" (world X east, Z south), worded as the engine words it. */
export function describeMoveMetres([dx, dz]: [number, number]): string {
  const parts: string[] = []
  if (Math.abs(dx) >= MOVE_TOL) parts.push(`${Math.abs(dx).toFixed(1)} m ${dx > 0 ? 'east' : 'west'}`)
  if (Math.abs(dz) >= MOVE_TOL) parts.push(`${Math.abs(dz).toFixed(1)} m ${dz > 0 ? 'south' : 'north'}`)
  return parts.join(', ')
}
