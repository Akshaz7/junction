import type { KgEdge, KgGraph, KgNode, KgNodeDetail } from './kg'

/** A small sample graph, generated for demo. Used only when VITE_PROJECTS_MOCK is set; the real server answers otherwise. */
export function mockGraph(projectId: string): KgGraph {
  const nodes: KgNode[] = []; const edges: KgEdge[] = []
  const node = (id: string, kind: string, label: string, extra: Partial<KgNode> = {}) => { const row: KgNode = { id, kind, label, doc_ids: [], level: null, props: {}, source: null, ...extra }; nodes.push(row); return row }
  const edge = (kind: string, from: KgNode | string, to: KgNode | string, method: string, confidence: number, evidence: Record<string, unknown> = {}, doc_ids: string[] = []) => { edges.push({ id: `e${edges.length + 1}`, kind, from: typeof from === 'string' ? from : from.id, to: typeof to === 'string' ? to : to.id, method, confidence, evidence, doc_ids }) }
  const project = node(`project:${projectId}:project`, 'project', 'Harbour Street 12', { doc_ids: ['model', 'plan', 'sched'] })
  const model = node('doc:model:doc', 'doc', 'Building model', { doc_ids: ['model'] })
  const plan = node('doc:plan:doc', 'doc', 'Level 1 plan', { doc_ids: ['plan'] })
  const sched = node('doc:sched:doc', 'doc', 'Door schedule', { doc_ids: ['sched'] })
  for (const doc of [model, plan, sched]) edge('contains', project, doc, 'rule', 1, { rule: 'project_file' })
  const levels = ['Level 1', 'Level 2'].map((name) => node(`level:project:${name}`, 'level', name, { level: name, doc_ids: ['model', 'plan'] }))
  levels.forEach((level) => { edge('contains', model, level, 'ifc_relation', 1, {}, ['model']) })
  edge('contains', plan, levels[0], 'level_name', 0.9, {}, ['plan'])
  const rooms = ['Lobby', 'Kitchen', 'Office 1', 'Office 2', 'Meeting room', 'Store', 'Bedroom', 'Bathroom'].map((name, index) => {
    const level = index < 5 ? 'Level 1' : 'Level 2'
    return node(`room:model:r${index}`, 'room', name, { level, doc_ids: ['model', 'plan'], props: { area_m2: 9 + index * 3.4, count_by_kind: { door: 1 + (index % 3), window: index % 2 ? 2 : 1 } }, source: { doc_id: 'model', page: 1, item_id: `r${index}` } })
  })
  rooms.forEach((room, index) => edge('on_level', room, levels[index < 5 ? 0 : 1], 'ifc_relation', 1, {}, ['model']))
  // Same rooms in the plan: matched by tag text or by position.
  const planRooms = rooms.slice(0, 5).map((room, index) => node(`room:plan:p${index}`, 'room', room.label, { level: 'Level 1', doc_ids: ['plan'], canonical: room.id, props: { area_m2: 9 + index * 3.4 + (index === 1 ? -1.8 : 0.1) }, source: { doc_id: 'plan', page: 1, item_id: `p${index}` } }))
  planRooms.forEach((room, index) => edge('same_as', room.id, rooms[index].id, index % 2 ? 'position' : 'tag_text', index % 2 ? [0.88, 0.55, 0.73][index === 1 ? 0 : index === 3 ? 1 : 2] : 0.97, index % 2 ? { residual_m: [0.4, 1.3, 0.2][index === 1 ? 0 : index === 3 ? 1 : 2] } : { tag: room.label }, ['model', 'plan']))
  const doors = Array.from({ length: 6 }, (_, index) => node(`door:model:d${index}`, 'door', `Door ${index + 1}`, { level: 'Level 1', doc_ids: ['model'], props: { width_m: 0.9 + (index % 2) * 0.1, height_m: 2.1 }, source: { doc_id: 'model', page: 1, item_id: `d${index}` } }))
  doors.forEach((door, index) => edge('in_room', door, rooms[index % 5].id, 'containment_geom', 0.93, {}, ['model']))
  doors.slice(0, 4).forEach((door, index) => edge('same_as', door, node(`door:sched:s${index}`, 'door', `Door ${index + 1} (schedule)`, { doc_ids: ['sched'], level: 'Level 1', canonical: door.id, props: { width_m: 0.9 + (index % 2) * 0.1 } }), 'tag_text', 0.95, { tag: `D${index + 1}` }, ['model', 'sched']))
  const windows = Array.from({ length: 4 }, (_, index) => node(`window:model:w${index}`, 'window', `Window ${index + 1}`, { level: 'Level 1', doc_ids: ['model'], props: { width_m: 1.2, height_m: 1.4 } }))
  windows.forEach((window, index) => edge('in_room', window, rooms[index].id, 'containment_geom', 0.91, {}, ['model']))
  const hvac = node('system:model:hvac', 'system', 'Supply air', { doc_ids: ['model'], props: { system: 'Ventilation', count: 3 } })
  ;[0, 2, 3].forEach((index) => { const outlet = node(`terminal:model:t${index}`, 'terminal', `Supply grille ${index + 1}`, { level: 'Level 1', doc_ids: ['model'] }); edge('part_of_system', outlet, hvac, 'ifc_relation', 1, {}, ['model']); edge('serves', outlet, rooms[index].id, 'position', index === 3 ? 0.52 : 0.84, { residual_m: index === 3 ? 1.9 : 0.5 }, ['model']) })
  const issue = node('issue:project:i1', 'issue', 'Kitchen area differs between files', { doc_ids: ['model', 'plan'], props: { severity: 'medium' } })
  edge('flags', issue, rooms[1].id, 'rule', 0.9, { rule: 'printed_vs_drawn_area' }, ['model', 'plan']); edge('flags', issue, planRooms[1].id, 'rule', 0.9, { rule: 'printed_vs_drawn_area' }, ['model', 'plan'])
  edge('differs', rooms[1].id, planRooms[1].id, 'rule', 0.9, { values: [13.4, 11.6], diff_pct: 13.4 }, ['model', 'plan'])
  edge('agrees', rooms[0].id, planRooms[0].id, 'rule', 0.9, { values: [9, 9.1], diff_pct: 1.1 }, ['model', 'plan'])
  const degree = new Map<string, number>(); edges.forEach((e) => { degree.set(e.from, (degree.get(e.from) ?? 0) + 1); degree.set(e.to, (degree.get(e.to) ?? 0) + 1) })
  nodes.forEach((n) => { n.degree = degree.get(n.id) ?? 0 })
  const by_kind: Record<string, number> = {}; nodes.forEach((n) => { by_kind[n.kind] = (by_kind[n.kind] ?? 0) + 1 })
  const linkable = nodes.filter((n) => !['project', 'doc', 'level', 'system', 'issue'].includes(n.kind))
  const linked = linkable.filter((n) => n.canonical || edges.some((e) => e.kind === 'same_as' && (e.from === n.id || e.to === n.id)))
  return { project_id: projectId, version: 1, built_at: new Date().toISOString(), nodes, edges, stats: { nodes: nodes.length, edges: edges.length, by_kind, linked_pct: Math.round((linked.length / linkable.length) * 100), agree_pct: 50, unlinked: [doors[4].id, doors[5].id, windows[3].id], issues: 1 } }
}
export const CLUSTER_KINDS = new Set(['project', 'doc', 'level', 'room', 'system', 'issue'])
export function mockCluster(graph: KgGraph): KgGraph {
  const nodes = graph.nodes.filter((node) => CLUSTER_KINDS.has(node.kind) && !node.canonical)
  const ids = new Set(nodes.map((node) => node.id))
  return { ...graph, nodes, edges: graph.edges.filter((edge) => ids.has(edge.from) && ids.has(edge.to)) }
}
export function mockNode(graph: KgGraph, id: string): KgNodeDetail {
  const node = graph.nodes.find((row) => row.id === id)
  if (!node) throw new Error('This item is not in the graph.')
  const byId = new Map(graph.nodes.map((row) => [row.id, row]))
  const neighbours = graph.edges.filter((edge) => edge.from === id || edge.to === id).map((edge) => ({ edge, node: byId.get(edge.from === id ? edge.to : edge.from)! })).filter((row) => row.node)
  return { node, neighbours }
}
