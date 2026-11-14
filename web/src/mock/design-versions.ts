/** Offline demo (VITE_USE_MOCK): saved design versions and their comparisons, kept in memory for this page load.
 *  Same routes and shapes as server/design_versions.py; the diff is by item id (lib/design-versions diffSnapshots). */
import { describeMoveMetres, diffSnapshots, type EditSnapshot } from '../lib/design-versions'
import type { Bbox } from '../lib/types'

export interface DemoDrawing { title: string; image: { w: number; h: number }; boxes: Record<string, Bbox> }
interface Version { n: number; parent: number; label: string; edits: EditSnapshot; created_at: string }

const store = new Map<string, Version[]>()
const EDITED = 'edited in 3D (generated from edits, not an issued drawing)'
const empty = (): EditSnapshot => ({ removed: [], moved: {}, materials: {} })

export function resetDemoVersions() { store.clear() }

function clean(body: unknown): EditSnapshot | null {
  if (!body || typeof body !== 'object') return null
  const b = body as Record<string, unknown>
  const removed = b.removed ?? [], moved = b.moved ?? {}, materials = b.materials ?? {}
  if (!Array.isArray(removed) || typeof moved !== 'object' || typeof materials !== 'object' || !moved || !materials) return null
  const m: Record<string, [number, number]> = {}
  for (const [id, v] of Object.entries(moved as Record<string, unknown>)) {
    if (!Array.isArray(v) || v.length !== 2 || !v.every((x) => Number.isFinite(x))) return null
    if (Math.abs(v[0]) >= 0.025 || Math.abs(v[1]) >= 0.025) m[id] = [Number(v[0]), Number(v[1])]
  }
  const t = Object.fromEntries(Object.entries(materials as Record<string, unknown>).filter(([, v]) => typeof v === 'string')) as Record<string, string>
  return { removed: [...new Set(removed.filter((id): id is string => typeof id === 'string'))].sort(), moved: m, materials: t }
}

const sameEdits = (a: EditSnapshot, b: EditSnapshot) => JSON.stringify(a) === JSON.stringify(b)
const counts = (changes: { action: string }[]) => Object.fromEntries((['removed', 'added', 'moved', 'material'] as const).map((k) => [k, changes.filter((c) => c.action === k).length])) as Record<'removed' | 'added' | 'moved' | 'material', number>
const versionsOf = (doc: string): (Version | { n: 0; parent: null; label: string; edits: EditSnapshot; created_at?: string })[] =>
  [{ n: 0, parent: null, label: 'Original', edits: empty() }, ...(store.get(doc) ?? [])]

function compare(doc: string, a: EditSnapshot, b: EditSnapshot, drawing?: DemoDrawing) {
  const shift = (box: Bbox | undefined, move?: [number, number]): Bbox | null => box ? (move ? [box[0] + move[0] * 40, box[1] + move[1] * 40, box[2] + move[0] * 40, box[3] + move[1] * 40] : box) : null
  return diffSnapshots(a, b).map((c, i) => {
    const box = drawing?.boxes[c.item_id], name = `Item ${c.item_id}`
    const sentence = c.action === 'removed' ? `${name} was removed.` : c.action === 'added' ? `${name} was added back.`
      : c.action === 'moved' ? `${name} moved ${describeMoveMetres(c.delta_m!)}.` : `${name} material changed from ${c.old || 'original'} to ${c.new || 'original'}.`
    const v1 = c.action === 'added' ? null : { item_id: c.item_id, bbox_px: shift(box, a.moved[c.item_id]) }
    const v2 = c.action === 'removed' ? null : { item_id: c.item_id, bbox_px: shift(box, b.moved[c.item_id]) }
    return { n: i + 1, change_id: `c${i + 1}`, type: c.action === 'removed' ? 'removed' : c.action === 'added' ? 'added' : 'modified', kind: 'item',
      sentence, description: sentence, edit: true, action: c.action, item_id: c.item_id, tag: null, page: box ? 1 : null, v1, v2, doc }
  })
}

/** Handles the design-version routes of the offline demo, or returns null for every other request. */
export async function handleDesignVersions(request: Request, drawings: Record<string, DemoDrawing>): Promise<Response | null> {
  const path = decodeURIComponent(new URL(request.url).pathname)
  let m = /^\/api\/docs\/([^/]+)\/versions$/.exec(path)
  if (m && request.method === 'GET') return Response.json({ doc_id: m[1], versions: versionsOf(m[1]) })
  if (m && request.method === 'POST') {
    const doc = m[1], body = await request.json().catch(() => null) as Record<string, unknown> | null
    const edits = clean(body)
    if (!edits) return Response.json({ detail: 'edits must be {removed, moved, materials}' }, { status: 400 })
    if (!edits.removed.length && !Object.keys(edits.moved).length && !Object.keys(edits.materials).length) return Response.json({ detail: 'No edits to save: remove or move an item first.' }, { status: 400 })
    const list = store.get(doc) ?? []
    const all = versionsOf(doc)
    let v = list.find((x) => sameEdits(x.edits, edits)), created = false
    if (!v) {
      const parent = typeof body?.parent === 'number' && all.some((x) => x.n === body.parent) ? body.parent : 0
      const n = list.length + 1, now = new Date().toISOString()
      v = { n, parent, label: `Edited version ${n} · ${now.slice(0, 10)}`, edits, created_at: now }
      store.set(doc, [...list, v]); created = true
    }
    const changes = compare(doc, all.find((x) => x.n === v!.parent)?.edits ?? empty(), v.edits, drawings[doc])
    return Response.json({ doc_id: doc, ...v, created, edited: true, generated: EDITED, change_id: `dv:${doc}:${v.parent}-${v.n}`,
      compare_url: `#/compare?change=${encodeURIComponent(`dv:${doc}:0-${v.n}`)}`, counts: counts(changes), n_changes: changes.length }, { status: created ? 201 : 200 })
  }
  if (path === '/api/changes' && request.method === 'GET') {
    const changes = [...store.entries()].flatMap(([doc, list]) => list.map((v) => {
      const all = versionsOf(doc), parent = all.find((x) => x.n === v.parent)!
      const diff = compare(doc, parent.edits, v.edits, drawings[doc])
      return { id: `dv:${doc}:${v.parent}-${v.n}`, type: 'new_version', doc_a: doc, doc_b: doc, created_at: v.created_at,
        summary: { doc_id: doc, series_id: `design:${doc}`, title: drawings[doc]?.title ?? doc, n_changes: diff.length, counts: counts(diff),
          headline: `${v.label}: ${diff.length} changes`, source: 'edit-diff', version_a: parent.label, version_b: v.label,
          index_a: v.parent, index_b: v.n, pair_prefix: `dv:${doc}:`, edited: true, generated: EDITED } }
    })).reverse()
    return Response.json({ changes })
  }
  m = /^\/api\/changes\/dv:([^:]+):(\d+)-(\d+)$/.exec(path)
  if (m && request.method === 'GET') {
    const [doc, a, b] = [m[1], Number(m[2]), Number(m[3])]
    const all = versionsOf(doc), va = all.find((x) => x.n === a), vb = all.find((x) => x.n === b)
    if (!va || !vb || a === b) return Response.json({ detail: 'change not found' }, { status: 404 })
    const changes = compare(doc, va.edits, vb.edits, drawings[doc])
    const drawing = drawings[doc], image = `/api/docs/${doc}/pages/1/image`
    const side = (v: typeof va) => ({ label: v.label, doc_id: doc, version: v.n, edited: v.n > 0, page_image: image, thumb: image })
    return Response.json({ id: `dv:${doc}:${a}-${b}`, type: 'new_version', doc_id: doc, series_id: `design:${doc}`, source: 'edit-diff',
      note: 'Compared item by item from the saved 3D edits (offline demo: the page shows the original drawing).', edited: true, generated: EDITED,
      generated_for_demo: true, image: drawing?.image ?? null, page: 1, pages: [{ page: 1, n_changes: changes.length }], counts: counts(changes),
      n_changes: changes.length, item_ids: changes.map((c) => c.item_id), v1: side(va), v2: side(vb), changes })
  }
  return null
}
