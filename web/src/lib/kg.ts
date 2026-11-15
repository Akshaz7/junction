/** Project knowledge graph: types (handoff/KG-CONTRACT.md v1) and the plain-code helpers the Graph tab uses. */

export type KgNodeKind = 'project' | 'doc' | 'level' | 'room' | 'door' | 'window' | 'wall' | 'slab' | 'stair' | 'column' | 'duct' | 'pipe' | 'terminal' | 'fixture' | 'system' | 'type' | 'material' | 'issue' | 'change' | 'sheet_ref'
export type KgEdgeKind = 'contains' | 'on_level' | 'in_room' | 'hosted_by' | 'bounds' | 'serves' | 'connects' | 'part_of_system' | 'same_as' | 'revision_of' | 'changed' | 'references' | 'agrees' | 'differs' | 'flags' | 'has_type' | 'made_of'
export type KgMethod = 'ifc_relation' | 'guid' | 'tag_text' | 'position' | 'label_text' | 'level_name' | 'containment_geom' | 'legend' | 'revision_compare' | 'rule' | 'model'

export type KgNode = {
  id: string; kind: KgNodeKind | string; label: string; doc_ids: string[]; level: string | null
  props: Record<string, unknown>
  source: { doc_id: string; page?: number | null; item_id?: string | null; bbox?: number[] | null } | null
  canonical?: string | null; degree?: number
}
export type KgEdge = { id: string; kind: KgEdgeKind | string; from: string; to: string; method: KgMethod | string; confidence: number; evidence: Record<string, unknown>; doc_ids: string[] }
export type KgStats = { nodes: number; edges: number; by_kind?: Record<string, number>; edges_by_kind?: Record<string, number>; linked_pct: number | null; agree_pct: number | null; counterpart_items?: number; linked_items?: number; unlinked: string[]; issues: number }
export type KgGraph = { project_id: string; version: number; built_at?: string; stats: KgStats; nodes: KgNode[]; edges: KgEdge[]; partial?: boolean }
export type KgNodeDetail = { node: KgNode; neighbours: { edge: KgEdge; node: KgNode }[]; path_to_project?: string[] }
export type KgGraphPath = { from_label: string; edge_kind: string; to_label: string; method?: string; confidence?: number }

/** Use project totals, never the subset of edges drawn in the cluster view. */
export function graphMatchMetrics(stats: KgStats) {
  const percent = (value: number) => `${Number(value.toFixed(1))}%`
  const matches = stats.edges_by_kind?.same_as ?? 0
  const agrees = stats.edges_by_kind?.agrees ?? 0
  const compared = agrees + (stats.edges_by_kind?.differs ?? 0)
  const linkedPct = stats.linked_pct ?? ((stats.counterpart_items ?? 0) > 0 ? 100 * (stats.linked_items ?? 0) / stats.counterpart_items! : null)
  const agreePct = stats.agree_pct ?? (compared ? 100 * agrees / compared : null)
  return {
    linked: linkedPct === 0 && (stats.counterpart_items ?? 0) > 0
      ? { value: 'None', hint: 'No item was found in more than one file. These files describe different parts of the building, or their items cannot be matched by id, label or position.' }
      : linkedPct != null
      ? { value: percent(linkedPct), hint: 'Items that appear in more than one file and are matched up' }
      : { value: matches.toLocaleString(), hint: matches ? 'Matching links across files. The share of matched items is not available.' : 'No items have been matched across files yet.' },
    agree: agreePct != null
      ? { value: percent(agreePct), hint: 'Compared values that agree between files' }
      : { value: '0', hint: 'No values have been compared between files yet.' },
  }
}

/** Below this an edge is an estimate: dashed in the view, and called an estimate in words. */
export const SOLID_CONFIDENCE = 0.6

/* ---- Plain English ---- */

const KIND_LABEL: Record<string, string> = {
  project: 'Project', doc: 'File', level: 'Level', room: 'Room', door: 'Door', window: 'Window', wall: 'Wall', slab: 'Floor slab', stair: 'Stair', column: 'Column',
  duct: 'Duct', pipe: 'Pipe', terminal: 'Outlet', fixture: 'Fixture', system: 'System', type: 'Type', material: 'Material', issue: 'Check these', change: 'Change', sheet_ref: 'Sheet reference',
}
export const kindLabel = (kind: string) => KIND_LABEL[kind] ?? kind.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase())
export const kindPlural = (kind: string) => ({ project: 'Projects', doc: 'Files', level: 'Levels', room: 'Rooms', door: 'Doors', window: 'Windows', wall: 'Walls', slab: 'Floor slabs', stair: 'Stairs', column: 'Columns', duct: 'Ducts', pipe: 'Pipes', terminal: 'Outlets', fixture: 'Fixtures', system: 'Systems', type: 'Types', material: 'Materials', issue: 'Issues', change: 'Changes', sheet_ref: 'Sheet references' } as Record<string, string>)[kind] ?? `${kindLabel(kind)}s`

/** Quiet colour groups, so the view is calm and not a rainbow. */
export type KindGroup = 'structure' | 'space' | 'element' | 'service' | 'issue'
const GROUP: Record<string, KindGroup> = {
  project: 'structure', doc: 'structure', level: 'structure', room: 'space',
  duct: 'service', pipe: 'service', terminal: 'service', system: 'service', issue: 'issue',
}
export const kindGroup = (kind: string): KindGroup => GROUP[kind] ?? 'element'
export const groupLabel: Record<KindGroup, string> = { structure: 'Files and levels', space: 'Rooms', element: 'Building elements', service: 'Services', issue: 'Issues' }
/** Existing design tokens for each group (read from CSS at draw time). */
export const groupToken: Record<KindGroup, string> = { structure: '--forest-950', space: '--forest-600', element: '--neutral-350', service: '--amber-600', issue: '--change-edited' }

const EDGE_OUT: Record<string, string> = {
  contains: 'contains', on_level: 'is on', in_room: 'is in', hosted_by: 'is hosted by', bounds: 'bounds', serves: 'serves', connects: 'connects to', part_of_system: 'is part of',
  same_as: 'is the same as', revision_of: 'is a revision of', changed: 'changed', references: 'refers to', agrees: 'agrees with', differs: 'differs from', flags: 'flags', has_type: 'has type', made_of: 'is made of',
}
const EDGE_IN: Record<string, string> = {
  contains: 'is contained in', on_level: 'has on it', in_room: 'has in it', hosted_by: 'hosts', bounds: 'is bounded by', serves: 'is served by', connects: 'connects to', part_of_system: 'includes', same_as: 'is the same as',
  revision_of: 'has revision', changed: 'was changed by', references: 'is referred to by', agrees: 'agrees with', differs: 'differs from', flags: 'is flagged by', has_type: 'is the type of', made_of: 'is the material of',
}
const GROUP_TITLE_OUT: Record<string, string> = {
  contains: 'Contains', on_level: 'On level', in_room: 'In room', hosted_by: 'Hosted by', bounds: 'Bounds', serves: 'Serves', connects: 'Connected to', part_of_system: 'Part of system', same_as: 'Same item in other files',
  revision_of: 'Revision of', changed: 'Changed', references: 'References', agrees: 'Agrees with', differs: 'Differs from', flags: 'Flags', has_type: 'Type', made_of: 'Made of',
}
const GROUP_TITLE_IN: Record<string, string> = {
  contains: 'Contained in', on_level: 'On this level', in_room: 'In this room', hosted_by: 'Hosts', bounds: 'Bounded by', serves: 'Served by', connects: 'Connected to', part_of_system: 'Includes', same_as: 'Same item in other files',
  revision_of: 'Revisions', changed: 'Changed by', references: 'Referred to by', agrees: 'Agrees with', differs: 'Differs from', flags: 'Flagged by', has_type: 'Used by', made_of: 'Used in',
}
export const edgeVerb = (kind: string, outgoing = true) => (outgoing ? EDGE_OUT : EDGE_IN)[kind] ?? kind.replace(/_/g, ' ')
export const edgeGroupTitle = (kind: string, outgoing = true) => (outgoing ? GROUP_TITLE_OUT : GROUP_TITLE_IN)[kind] ?? kind.replace(/_/g, ' ')

const num = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null)
function metres(value: number) { return `${value < 0.1 ? value.toFixed(3) : value.toFixed(value < 1 ? 2 : 1).replace(/\.0$/, '')} m` }

/** "matched by position, 0.4 m apart": how a link was made, in words a site manager can read. */
export function methodPhrase(edge: Pick<KgEdge, 'method' | 'evidence'>): string {
  const evidence = edge.evidence ?? {}
  switch (edge.method) {
    case 'ifc_relation': return 'stated in the model'
    case 'guid': return 'same ID in both files'
    case 'tag_text': return typeof evidence.tag === 'string' && evidence.tag ? `matched by the tag "${evidence.tag}"` : 'matched by the tag text'
    case 'label_text': return typeof evidence.label === 'string' && evidence.label ? `matched by the label "${evidence.label}"` : 'matched by the label text'
    case 'level_name': return 'matched by level name'
    case 'containment_geom': return 'sits inside its outline'
    case 'legend': return 'read from the legend'
    case 'revision_compare': return 'found by comparing the revisions'
    case 'position': {
      const alignment = evidence.alignment && typeof evidence.alignment === 'object' ? evidence.alignment as Record<string, unknown> : {}
      const residual = num(evidence.residual_m) ?? num(alignment.residual)
      return residual == null ? 'matched by position' : `matched by position, ${metres(residual)} apart`
    }
    case 'rule': return typeof evidence.rule === 'string' && evidence.rule ? `by rule: ${evidence.rule.replace(/_/g, ' ')}` : 'by a fixed rule'
    case 'model': return 'read by an AI model'
    default: return String(edge.method ?? '').replace(/_/g, ' ')
  }
}
export const confidencePct = (confidence: number) => Math.round(Math.max(0, Math.min(1, confidence)) * 100)
export const isEstimate = (edge: Pick<KgEdge, 'confidence'>) => edge.confidence < SOLID_CONFIDENCE
/** Stats come as a fraction or a percent; show both the same way. */
export const asPercent = (value: number | null | undefined): number | null => value == null || !Number.isFinite(value) ? null : Math.round(value <= 1 ? value * 100 : value)

/** One plain line for a property, with its unit. Hidden for internal values. */
const PROP_LABEL: Record<string, string> = { area_m2: 'Area', count: 'Count', width_m: 'Width', height_m: 'Height', length_m: 'Length', volume_m3: 'Volume', thickness_m: 'Thickness', system: 'System', type: 'Type', material: 'Material' }
export function propLines(props: Record<string, unknown>): { label: string; value: string }[] {
  const lines: { label: string; value: string }[] = []
  for (const [key, value] of Object.entries(props ?? {})) {
    if (value == null || value === '' || typeof value === 'object') continue
    const label = PROP_LABEL[key] ?? key.replace(/_(m2|m3|m)$/, '').replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase())
    if (typeof value === 'number') {
      const text = Number.isInteger(value) ? String(value) : value.toFixed(2).replace(/0+$/, '').replace(/\.$/, '')
      lines.push({ label, value: key.endsWith('_m2') ? `${text} m²` : key.endsWith('_m3') ? `${text} m³` : key.endsWith('_m') ? `${text} m` : text })
    } else if (typeof value === 'string' || typeof value === 'boolean') lines.push({ label, value: String(value) })
  }
  return lines
}
export function countByKind(props: Record<string, unknown>): { kind: string; count: number }[] {
  const raw = props?.count_by_kind
  if (!raw || typeof raw !== 'object') return []
  return Object.entries(raw as Record<string, unknown>).map(([kind, count]) => ({ kind, count: Number(count) })).filter((row) => row.count > 0).sort((a, b) => b.count - a.count)
}

/* ---- Graph helpers ---- */

export type Neighbour = { edge: KgEdge; node: KgNode; outgoing: boolean }
export function indexGraph(nodes: KgNode[], edges: KgEdge[]) {
  const byId = new Map(nodes.map((node) => [node.id, node]))
  const adjacency = new Map<string, Neighbour[]>()
  for (const edge of edges) {
    const from = byId.get(edge.from); const to = byId.get(edge.to)
    if (!from || !to) continue
    ;(adjacency.get(from.id) ?? adjacency.set(from.id, []).get(from.id)!).push({ edge, node: to, outgoing: true })
    ;(adjacency.get(to.id) ?? adjacency.set(to.id, []).get(to.id)!).push({ edge, node: from, outgoing: false })
  }
  return { byId, adjacency }
}
/** Connections of one item, grouped by what kind of link it is. */
export function groupConnections(neighbours: Neighbour[]): { key: string; title: string; items: Neighbour[] }[] {
  const groups = new Map<string, { key: string; title: string; items: Neighbour[] }>()
  for (const item of neighbours) {
    const symmetric = item.edge.kind === 'connects' || item.edge.kind === 'same_as' || item.edge.kind === 'agrees' || item.edge.kind === 'differs'
    const key = `${item.edge.kind}:${symmetric || item.outgoing ? 'out' : 'in'}`
    const group = groups.get(key) ?? groups.set(key, { key, title: edgeGroupTitle(item.edge.kind, symmetric || item.outgoing), items: [] }).get(key)!
    group.items.push(item)
  }
  for (const group of groups.values()) group.items.sort((a, b) => b.edge.confidence - a.edge.confidence || a.node.label.localeCompare(b.node.label))
  return [...groups.values()]
}

export type GraphFilters = { groups: Set<KindGroup>; level: string; doc: string }
export const noFilters = (): GraphFilters => ({ groups: new Set(), level: '', doc: '' })
export const filtersActive = (filters: GraphFilters) => filters.groups.size > 0 || !!filters.level || !!filters.doc
/** Filters keep the hub nodes (project, files, levels) of what is left, so the picture stays connected. */
export function filterGraph(nodes: KgNode[], edges: KgEdge[], filters: GraphFilters): { nodes: KgNode[]; edges: KgEdge[] } {
  if (!filtersActive(filters)) return { nodes, edges }
  const keep = (node: KgNode) => {
    if (node.kind === 'project') return true
    if (node.kind === 'doc') return !filters.doc || node.doc_ids.includes(filters.doc)
    if (node.kind === 'level') return !filters.level || node.label === filters.level
    if (filters.groups.size && !filters.groups.has(kindGroup(node.kind))) return false
    if (filters.level && node.level !== filters.level) return false
    if (filters.doc && !node.doc_ids.includes(filters.doc)) return false
    return true
  }
  const kept = nodes.filter(keep)
  const ids = new Set(kept.map((node) => node.id))
  return { nodes: kept, edges: edges.filter((edge) => ids.has(edge.from) && ids.has(edge.to)) }
}
export function searchNodes(nodes: KgNode[], query: string, limit = 8): KgNode[] {
  const text = query.trim().toLowerCase()
  if (!text) return []
  const scored: [number, KgNode][] = []
  for (const node of nodes) {
    const label = node.label.toLowerCase()
    const at = label.indexOf(text)
    if (at < 0 && !kindLabel(node.kind).toLowerCase().includes(text)) continue
    scored.push([at < 0 ? 100 : at === 0 ? 0 : 1 + at / 100, node])
  }
  return scored.sort((a, b) => a[0] - b[0] || (b[1].degree ?? 0) - (a[1].degree ?? 0)).slice(0, limit).map((row) => row[1])
}
export function degrees(nodes: KgNode[], edges: KgEdge[]): Map<string, number> {
  const result = new Map(nodes.map((node) => [node.id, 0]))
  for (const edge of edges) { if (result.has(edge.from)) result.set(edge.from, (result.get(edge.from) ?? 0) + 1); if (result.has(edge.to)) result.set(edge.to, (result.get(edge.to) ?? 0) + 1) }
  return result
}
/** Radius from degree: gentle, so a hub is larger but never huge. */
export const nodeRadius = (degree: number, kind: string) => (kind === 'project' ? 11 : 4 + Math.min(9, Math.sqrt(Math.max(0, degree)) * 1.5))
/** Add new nodes and edges to what is shown, without duplicates. */
export function mergeGraph(shown: { nodes: KgNode[]; edges: KgEdge[] }, more: { nodes: KgNode[]; edges: KgEdge[] }) {
  const nodeIds = new Set(shown.nodes.map((node) => node.id)); const edgeIds = new Set(shown.edges.map((edge) => edge.id))
  const nodes = [...shown.nodes, ...more.nodes.filter((node) => !nodeIds.has(node.id))]
  const ids = new Set(nodes.map((node) => node.id))
  const edges = [...shown.edges, ...more.edges.filter((edge) => !edgeIds.has(edge.id) && ids.has(edge.from) && ids.has(edge.to))]
  return { nodes, edges }
}
/** The chain of a graph answer as one line: "Supply grille 12 serves Room 104". */
export function pathLine(step: KgGraphPath) { return `${step.from_label} ${edgeVerb(step.edge_kind)} ${step.to_label}` }
