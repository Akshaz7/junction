import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Search, X } from 'lucide-react'
import { Button } from './ui'
import { ErrorLine, Skeleton } from './project-parts'
import { GraphCanvas, type GraphCanvasHandle } from './kg-canvas'
import {
  confidencePct, countByKind, edgeVerb, filterGraph, filtersActive, graphMatchMetrics, groupConnections, groupLabel, indexGraph, isEstimate, kindGroup, kindLabel, kindPlural, mergeGraph, methodPhrase, noFilters, propLines, searchNodes,
  type GraphFilters, type KgGraph, type KgNode, type KgNodeDetail, type KindGroup,
} from '../lib/kg'
import { projectsApi, projectsMock, type Project } from '../lib/projects-api'
import { docTitle } from '../lib/projects-format'
import { displayNodes, levelDisplay } from '../lib/kg-display'
import { useProjectGraph } from './use-project-graph'
import './project-graph.css'

const FILTER_GROUPS: KindGroup[] = ['space', 'element', 'service', 'issue']
const EXPAND_LIMIT = 40
const ALL_LIMIT = 2000

function StatsStrip({ graph, onUnlinked, active }: { graph: KgGraph; onUnlinked: () => void; active: boolean }) {
  const { stats } = graph
  const by = stats.by_kind ?? {}
  const structural = (by.project ?? 0) + (by.doc ?? 0) + (by.level ?? 0)
  const items = by.project != null || by.doc != null ? Math.max(0, stats.nodes - structural) : stats.nodes
  const check = stats.unlinked?.length ?? 0
  const metrics = graphMatchMetrics(stats)
  const tiles: [string, string, string?][] = [['Items', items.toLocaleString()], ['Links', stats.edges.toLocaleString()], ['Linked across files', metrics.linked.value, metrics.linked.hint], ['Values agree', metrics.agree.value, metrics.agree.hint], ['Open issues', String(stats.issues ?? 0)]]
  return <div className="overview-stats pj-stats kg-stats" aria-label="Graph totals">
    {tiles.map(([label, value, hint]) => <div className="overview-stat" key={label} title={hint}><strong>{value}</strong><span>{label}</span></div>)}
    <button type="button" className={`overview-stat kg-check${active ? ' is-active' : ''}`} disabled={!check} aria-pressed={active} onClick={onUnlinked} title="Items that could not be matched to another file"><strong>{check}</strong><span>Check these</span></button>
  </div>
}

function Crop({ docId, page, bbox }: { docId: string; page: number; bbox: number[] }) {
  const [box, setBox] = useState<{ w: number; h: number } | null>(null)
  const src = `/api/docs/${encodeURIComponent(docId)}/pages/${page}/image`
  useEffect(() => {
    let live = true
    const image = new Image()
    image.onload = () => { if (live) setBox({ w: image.naturalWidth, h: image.naturalHeight }) }
    image.src = src
    return () => { live = false }
  }, [src])
  if (!box || bbox.length < 4) return null
  const [x0, y0, x1, y1] = bbox
  const padX = Math.max(24, (x1 - x0) * 0.6); const padY = Math.max(24, (y1 - y0) * 0.6)
  const left = Math.max(0, x0 - padX); const top = Math.max(0, y0 - padY)
  const width = Math.min(box.w, x1 + padX) - left; const height = Math.min(box.h, y1 + padY) - top
  if (width <= 0 || height <= 0) return null
  const scale = Math.min(1, 264 / width)
  return <div className="kg-crop" role="img" aria-label="Where this item is on the drawing" style={{ width: width * scale, height: Math.min(180, height * scale), backgroundImage: `url(${src})`, backgroundSize: `${box.w * scale}px ${box.h * scale}px`, backgroundPosition: `${-left * scale}px ${-top * scale}px` }}>
    <span style={{ left: (x0 - left) * scale, top: (y0 - top) * scale, width: (x1 - x0) * scale, height: (y1 - y0) * scale }} />
  </div>
}

function ifcClass(props: Record<string, unknown> | undefined): string {
  const key = Object.keys(props ?? {}).find((name) => name.toLowerCase().replace(/[^a-z]/g, '') === 'ifcclass')
  const value = key ? props?.[key] : undefined
  return typeof value === 'string' && /^Ifc/.test(value) ? value : ''
}

function Connections({ detail, onSelect }: { detail: KgNodeDetail; onSelect: (id: string, detail: KgNodeDetail) => void }) {
  const groups = useMemo(() => groupConnections(detail.neighbours.map((item) => ({ ...item, outgoing: item.edge.from === detail.node.id }))), [detail])
  const [open, setOpen] = useState<Set<string>>(new Set())
  if (!groups.length) return <p className="pj-hint">No connections yet.</p>
  return <div className="kg-groups">{groups.map((group) => {
    const more = open.has(group.key); const rows = more ? group.items : group.items.slice(0, 5)
    return <section key={group.key} aria-label={group.title}>
      <h4>{group.title} <span>{group.items.length}</span></h4>
      <ul>{rows.map(({ edge, node }) => <li key={edge.id}>
        <button type="button" onClick={() => onSelect(node.id, detail)}>
          <span className="kg-dot" data-group={kindGroup(node.kind)} aria-hidden="true" />
          <span className="kg-link-text"><strong title={node.label}>{node.label}</strong>
            <small>{kindLabel(node.kind)}{node.level && node.level !== node.label ? ` · ${node.level}` : ''}</small></span>
        </button>
        <p className="kg-method">{methodPhrase(edge)}<span className={isEstimate(edge) ? 'is-estimate' : ''}>{isEstimate(edge) ? `Estimate · ${confidencePct(edge.confidence)}%` : `${confidencePct(edge.confidence)}%`}</span></p>
      </li>)}</ul>
      {group.items.length > 5 && <button type="button" className="kg-more" onClick={() => setOpen((prev) => { const next = new Set(prev); if (next.has(group.key)) next.delete(group.key); else next.add(group.key); return next })}>{more ? 'Show fewer' : `Show ${group.items.length - 5} more`}</button>}
    </section>
  })}</div>
}

function NodePanel({ project, node, detail, loading, error, canShow3d, onClose, onSelect, onShow, onAsk }: {
  project: Project; node: KgNode; detail: KgNodeDetail | null; loading: boolean; error: string; canShow3d: (docId: string) => boolean
  onClose: () => void; onSelect: (id: string, detail: KgNodeDetail) => void; onShow: (docId: string, itemIds: string[], mode?: '2d' | '3d') => void; onAsk: (text: string) => void
}) {
  const shown = detail?.node ?? node
  const docId = shown.source?.doc_id ?? shown.doc_ids[0] ?? null
  const itemIds = shown.source?.item_id ? [shown.source.item_id] : []
  const doc = docId ? project.docs.find((row) => row.doc_id === docId) : undefined
  const lines = propLines(shown.props); const counts = countByKind(shown.props)
  const canOpen = !!docId && !!doc
  return <aside className="kg-panel" aria-label="Item details">
    <header>
      <div><span className="kg-kind"><span className="kg-dot" data-group={kindGroup(shown.kind)} aria-hidden="true" />{kindLabel(shown.kind)}{ifcClass(shown.props) ? ` (${ifcClass(shown.props)})` : ''}{shown.level ? ` · ${shown.level}` : ''}</span>
        <h3 title={shown.label}>{shown.kind === 'level' ? levelDisplay(shown.label) : shown.label}</h3></div>
      <Button variant="ghost" size="icon-sm" aria-label="Close details" onClick={onClose}><X size={16} /></Button>
    </header>
    <div className="kg-panel-actions">
      <Button variant="outline" disabled={!canOpen} onClick={() => docId && onShow(docId, itemIds, '2d')}>Show in drawing</Button>
      {docId && canShow3d(docId) && <Button variant="outline" onClick={() => onShow(docId, itemIds, '3d')}>Show in 3D</Button>}
      <Button variant="outline" onClick={() => onAsk(`Tell me about ${shown.label}`)}>Ask about this</Button>
    </div>
    {doc && <section className="kg-source" aria-label="Source"><h4>Source</h4>
      <p><strong title={docTitle(doc)}>{docTitle(doc)}</strong>{shown.source?.page ? <span> · page {shown.source.page}</span> : null}</p>
      {shown.source?.doc_id && shown.source.page && shown.source.bbox ? <Crop docId={shown.source.doc_id} page={shown.source.page} bbox={shown.source.bbox} /> : null}</section>}
    {(lines.length > 0 || counts.length > 0) && <section aria-label="Properties"><h4>Properties</h4>
      <dl className="kg-props">{lines.map((line) => <div key={line.label}><dt>{line.label}</dt><dd>{line.value}</dd></div>)}
        {counts.map((row) => <div key={row.kind}><dt>{kindPlural(row.kind)}</dt><dd>{row.count}</dd></div>)}</dl></section>}
    <section aria-label="Connections"><h4>Connections</h4>
      {loading && !detail ? <Skeleton lines={4} /> : error ? <ErrorLine message={error} /> : detail ? <Connections detail={detail} onSelect={onSelect} /> : null}</section>
  </aside>
}

function UnlinkedPanel({ nodes, onSelect, onClose }: { nodes: KgNode[]; onSelect: (id: string) => void; onClose: () => void }) {
  return <aside className="kg-panel" aria-label="Check these">
    <header><div><h3>Check these</h3><p className="pj-hint">These could not be matched to an item in another file. Open one to see where it is.</p></div>
      <Button variant="ghost" size="icon-sm" aria-label="Close list" onClick={onClose}><X size={16} /></Button></header>
    {nodes.length ? <ul className="kg-unlinked">{nodes.map((node) => <li key={node.id}><button type="button" onClick={() => onSelect(node.id)}><span className="kg-dot" data-group={kindGroup(node.kind)} aria-hidden="true" /><span className="kg-link-text"><strong title={node.label}>{node.label}</strong><small>{kindLabel(node.kind)}{node.level ? ` · ${node.level}` : ''}</small></span></button></li>)}</ul> : <Skeleton lines={4} />}
  </aside>
}

function Legend() {
  return <ul className="kg-legend" aria-label="Legend">
    {(['structure', ...FILTER_GROUPS] as KindGroup[]).map((group) => <li key={group}><span className="kg-dot" data-group={group} aria-hidden="true" />{groupLabel[group]}</li>)}
    <li><svg width="22" height="8" aria-hidden="true"><line x1="0" y1="4" x2="22" y2="4" stroke="currentColor" strokeWidth="1.5" /></svg>Link</li>
    <li><svg width="22" height="8" aria-hidden="true"><line x1="0" y1="4" x2="22" y2="4" stroke="currentColor" strokeWidth="1.5" strokeDasharray="4 3" /></svg>Estimate</li>
  </ul>
}

/** The project's knowledge graph: how its files and the items inside them connect. */
export function GraphTab({ project, focus = [], onShow, onAsk, canShow3d }: {
  project: Project; focus?: string[]
  onShow: (docId: string, itemIds?: string[], mode?: '2d' | '3d') => void; onAsk: (text: string) => void; canShow3d?: (docId: string) => boolean
}) {
  const { graph, error, slow, pending, retry } = useProjectGraph(project.id, project.docs.length)
  const [shown, setShown] = useState<{ nodes: KgNode[]; edges: KgGraph['edges'] }>({ nodes: [], edges: [] })
  const [mode, setMode] = useState<'overview' | 'all'>('overview')
  const [filters, setFilters] = useState<GraphFilters>(noFilters)
  const [query, setQuery] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [panel, setPanel] = useState<'node' | 'unlinked'>('node')
  const [detail, setDetail] = useState<{ id: string; data?: KgNodeDetail; error: string } | null>(null)
  const [notice, setNotice] = useState('')
  const [marked, setMarked] = useState<ReadonlySet<string>>(new Set())
  const full = useRef<KgGraph | null>(null)
  const fullLoading = useRef<Promise<KgGraph | null> | null>(null)
  const handle = useRef<GraphCanvasHandle>(null)
  const [fullVersion, setFullVersion] = useState(0)

  const ensureFull = useCallback(async () => {
    if (full.current) return full.current
    fullLoading.current ??= projectsApi.graph(project.id, { depth: 'full' }).then((next) => { full.current = next; setFullVersion((value) => value + 1); return next }).catch(() => null).finally(() => { fullLoading.current = null })
    return fullLoading.current
  }, [project.id])

  useEffect(() => { full.current = null; setMode('overview'); setSelectedId(null); setPanel('node'); setFilters(noFilters()) }, [project.id])
  useEffect(() => { if (graph) { setShown({ nodes: graph.nodes, edges: graph.edges }); setMode('overview') } }, [graph])

  const known = useMemo(() => {
    void fullVersion
    return indexGraph(full.current?.nodes ?? shown.nodes, full.current?.edges ?? shown.edges)
  }, [fullVersion, shown])
  const docTitles = useMemo(() => new Map(project.docs.map((doc) => [doc.doc_id, docTitle(doc)] as const)), [project.docs])
  const visible = useMemo(() => { const out = filterGraph(shown.nodes, shown.edges, filters); return { ...out, nodes: displayNodes(out.nodes, docTitles) } }, [shown, filters, docTitles])
  const levels = useMemo(() => [...new Set((full.current?.nodes ?? shown.nodes).filter((node) => node.kind === 'level').map((node) => node.label))].sort(), [shown, fullVersion])
  const docs = useMemo(() => project.docs.map((doc) => ({ id: doc.doc_id, title: docTitle(doc) })), [project.docs])
  const selectedNode = selectedId ? known.byId.get(selectedId) ?? shown.nodes.find((node) => node.id === selectedId) ?? null : null

  // Details for the selected item: its real connections, including ones not drawn yet.
  useEffect(() => {
    if (!selectedId) { setDetail(null); return }
    let live = true
    setDetail({ id: selectedId, error: '' })
    projectsApi.graphNode(project.id, selectedId).then((data) => { if (live) setDetail({ id: selectedId, data, error: '' }) })
      .catch((err: unknown) => { if (live) setDetail({ id: selectedId, error: err instanceof Error ? err.message : 'Connections could not be loaded.' }) })
    return () => { live = false }
  }, [project.id, selectedId])

  /** Draw an item (and the links to what is already drawn) so it can be selected. */
  const reveal = useCallback(async (id: string, data?: KgNodeDetail) => {
    let detailData = data
    if (!detailData || detailData.node.id !== id) {
      try { detailData = await projectsApi.graphNode(project.id, id) } catch { detailData = undefined }
    }
    if (detailData) {
      const found = detailData
      setShown((prev) => {
        const ids = new Set(prev.nodes.map((node) => node.id))
        return mergeGraph(prev, { nodes: [found.node], edges: found.neighbours.filter((row) => ids.has(row.node.id)).map((row) => row.edge) })
      })
    }
    setPanel('node'); setSelectedId(id)
    setTimeout(() => handle.current?.fit([id]), 420)
  }, [project.id])

  const expand = useCallback(async (id: string) => {
    setSelectedId(id); setPanel('node')
    try {
      const data = await projectsApi.graphNode(project.id, id)
      const rows = [...data.neighbours].sort((a, b) => b.edge.confidence - a.edge.confidence)
      const take = rows.slice(0, EXPAND_LIMIT)
      setShown((prev) => mergeGraph(prev, { nodes: [data.node, ...take.map((row) => row.node)], edges: take.map((row) => row.edge) }))
      setNotice(rows.length > take.length ? `Showing the ${take.length} most certain of ${rows.length} connections. The panel lists all of them.` : '')
    } catch (err) { setNotice(err instanceof Error ? err.message : 'Could not expand this item.') }
  }, [project.id])

  const toggleAll = useCallback(async () => {
    if (mode === 'all') { if (graph) setShown({ nodes: graph.nodes, edges: graph.edges }); setMode('overview'); setNotice(''); return }
    setNotice('Loading every item…')
    const next = await ensureFull()
    if (!next) { setNotice('Every item could not be loaded.'); return }
    const nodes = next.nodes.length > ALL_LIMIT ? [...next.nodes].sort((a, b) => (b.degree ?? 0) - (a.degree ?? 0)).slice(0, ALL_LIMIT) : next.nodes
    setShown({ nodes, edges: next.edges }); setMode('all')
    setNotice(next.nodes.length > ALL_LIMIT ? `Showing the ${ALL_LIMIT.toLocaleString()} best connected of ${next.nodes.length.toLocaleString()} items. Search finds the rest.` : '')
  }, [mode, graph, ensureFull])

  // Search looks in every item, not only what is drawn.
  const [hits, setHits] = useState<KgNode[]>([])
  useEffect(() => {
    if (!query.trim()) { setHits([]); return }
    let live = true
    void ensureFull().then((next) => { if (live) setHits(searchNodes(next?.nodes ?? shown.nodes, query)) })
    setHits(searchNodes(shown.nodes, query))
    return () => { live = false }
  }, [query, ensureFull, shown.nodes])

  // Coming from an answer: draw the items it used, mark them and look at them.
  const focusKey = focus.join('|')
  useEffect(() => {
    if (!focus.length || !graph) return
    let live = true
    void ensureFull().then((next) => {
      if (!live || !next) return
      const byLabel = new Map(next.nodes.map((node) => [node.label.toLowerCase(), node]))
      const ids = new Set(next.nodes.map((node) => node.id))
      const found = focus.map((value) => (ids.has(value) ? value : byLabel.get(value.toLowerCase())?.id)).filter((value): value is string => !!value)
      if (!found.length) { setNotice('The items from this answer are not in the graph yet.'); return }
      const wanted = new Set(found)
      const edges = next.edges.filter((edge) => wanted.has(edge.from) || wanted.has(edge.to))
      const nodeIds = new Set([...wanted, ...edges.flatMap((edge) => [edge.from, edge.to])])
      const nodes = next.nodes.filter((node) => nodeIds.has(node.id))
      setShown((prev) => mergeGraph(prev, { nodes, edges })); setMarked(wanted); setSelectedId(found[0]); setPanel('node')
      setTimeout(() => handle.current?.fit([...nodeIds]), 600)
    })
    return () => { live = false }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusKey, graph, ensureFull])

  const [unlinkedNodes, setUnlinkedNodes] = useState<KgNode[]>([])
  async function showUnlinked() {
    if (panel === 'unlinked') { setPanel('node'); return }
    setPanel('unlinked'); setSelectedId(null)
    const next = await ensureFull()
    const byId = new Map((next?.nodes ?? shown.nodes).map((node) => [node.id, node]))
    setUnlinkedNodes((graph?.stats.unlinked ?? []).map((id) => byId.get(id)).filter((node): node is KgNode => !!node))
  }

  const toggleGroup = (group: KindGroup) => setFilters((prev) => { const groups = new Set(prev.groups); if (groups.has(group)) groups.delete(group); else groups.add(group); return { ...prev, groups } })

  if (!project.docs.length) return <div className="pj-empty" data-testid="graph-empty"><h2>No graph yet</h2><p>Add plans, models or scans to this project and their items are linked here.</p></div>
  if (error && !graph) return <ErrorLine message={error} onRetry={retry} />
  if (!graph) return <div className="kg-loading" aria-busy="true" aria-label="Building the graph">{slow && <p className="pj-hint" role="status">Still loading the graph. <button type="button" className="pj-link" onClick={retry}>Try again</button></p>}<div className="overview-stats pj-stats kg-stats">{[0, 1, 2, 3, 4, 5].map((n) => <div key={n} className="overview-stat"><Skeleton lines={2} /></div>)}</div><div className="kg-stage"><Skeleton lines={4} className="kg-skel" /></div></div>
  if (!graph.nodes.length) return <div className="pj-empty" data-testid="graph-empty"><h2>{graph.partial ? 'Linking the files…' : 'No links found yet'}</h2><p>{graph.partial ? 'The graph is still being built. It appears here when it is ready.' : 'The files in this project have nothing in common that could be linked.'}</p></div>

  return <div className="kg" data-testid="graph-tab">
    <StatsStrip graph={graph} active={panel === 'unlinked'} onUnlinked={() => void showUnlinked()} />
    <div className="kg-toolbar" role="search">
      <div className="pj-search kg-search"><Search size={15} aria-hidden="true" />
        <input type="search" aria-label="Search the graph" placeholder="Search rooms, doors, systems…" value={query} onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => { if (event.key === 'Enter' && hits[0]) { void reveal(hits[0].id); setQuery('') } else if (event.key === 'Escape') setQuery('') }} />
        {query.trim() && hits.length > 0 && <ul className="kg-hits" role="listbox" aria-label="Search results">{hits.map((node) => <li key={node.id} role="option" aria-selected="false"><button type="button" onClick={() => { void reveal(node.id); setQuery('') }}><span className="kg-dot" data-group={kindGroup(node.kind)} aria-hidden="true" /><strong>{node.label}</strong><small>{kindLabel(node.kind)}{node.level ? ` · ${node.level}` : ''}</small></button></li>)}</ul>}
        {query.trim() && hits.length === 0 && <p className="kg-hits kg-no-hits" role="status">Nothing matches</p>}
      </div>
      <div className="kg-chips" role="group" aria-label="Show">{FILTER_GROUPS.map((group) => <button key={group} type="button" aria-pressed={filters.groups.has(group)} onClick={() => toggleGroup(group)}>{groupLabel[group]}</button>)}</div>
      <select aria-label="Level" value={filters.level} onChange={(event) => setFilters((prev) => ({ ...prev, level: event.target.value }))}><option value="">All levels</option>{levels.map((level) => <option key={level} value={level}>{levelDisplay(level)}</option>)}</select>
      <select aria-label="File" value={filters.doc} onChange={(event) => setFilters((prev) => ({ ...prev, doc: event.target.value }))}><option value="">All files</option>{docs.map((doc) => <option key={doc.id} value={doc.id}>{doc.title}</option>)}</select>
      {filtersActive(filters) && <Button variant="ghost" onClick={() => setFilters(noFilters())}>Clear</Button>}
      <Button variant="outline" className="kg-all" aria-pressed={mode === 'all'} onClick={() => void toggleAll()}>{mode === 'all' ? 'Overview' : 'Show all items'}</Button>
    </div>
    <div className={`kg-stage${selectedNode || panel === 'unlinked' ? ' has-panel' : ''}`}>
      <div className="kg-graph">
        <GraphCanvas nodes={visible.nodes} edges={visible.edges} selectedId={selectedId} markedIds={marked} handle={handle}
          label={`Knowledge graph of ${project.name}: ${visible.nodes.length} items and ${visible.edges.length} links. Use search or the Check these list to open an item.`}
          onSelect={(id) => { setPanel('node'); setSelectedId(id) }} onExpand={(id) => void expand(id)} />
        {visible.nodes.length <= 1 && <p className="kg-note">Nothing to show with these filters.</p>}
      </div>
      {panel === 'unlinked' ? <UnlinkedPanel nodes={unlinkedNodes} onSelect={(id) => void reveal(id)} onClose={() => setPanel('node')} />
        : selectedNode ? <NodePanel project={project} node={selectedNode} detail={detail?.id === selectedNode.id ? detail.data ?? null : null} loading={detail?.id === selectedNode.id && !detail.data && !detail.error} error={detail?.id === selectedNode.id ? detail.error : ''}
          canShow3d={canShow3d ?? ((docId) => { const doc = project.docs.find((row) => row.doc_id === docId); return !!doc && (doc.kind === 'ifc' || doc.formats.includes('ifc')) })}
          onClose={() => { setSelectedId(null); setMarked(new Set()) }} onSelect={(id, data) => void reveal(id, data.node.id === id ? data : undefined)} onShow={onShow} onAsk={onAsk} /> : null}
    </div>
    <div className="kg-foot"><Legend />{pending && <p className="pj-hint kg-updating" role="status">Updating…</p>}<p className="pj-hint" role="status">{notice || (projectsMock ? 'Sample graph, generated for demo. Click an item for details, double-click to expand it.' : 'Click an item for details, double-click to expand it. Dashed links are estimates.')}</p></div>
  </div>
}

export { edgeVerb }
