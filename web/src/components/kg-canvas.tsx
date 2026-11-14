import { useCallback, useEffect, useImperativeHandle, useRef, type Ref } from 'react'
import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY, type Simulation, type SimulationLinkDatum, type SimulationNodeDatum } from 'd3-force'
import { Maximize2, Minus, Plus } from 'lucide-react'
import { Button } from './ui'
import { degrees, groupToken, isEstimate, kindGroup, nodeRadius, type KgEdge, type KgNode } from '../lib/kg'

type SimNode = SimulationNodeDatum & { id: string; kind: string; label: string; r: number; group: ReturnType<typeof kindGroup>; hub: boolean }
type SimLink = SimulationLinkDatum<SimNode> & { edge: KgEdge }
type Camera = { x: number; y: number; k: number }

export type GraphCanvasHandle = { fit: (ids?: string[]) => void; zoomBy: (factor: number) => void }

/** Force-directed graph on canvas (d3-force, ISC). Hover lights a node and its neighbours; click selects; double click expands. */
export function GraphCanvas({ nodes, edges, selectedId, markedIds, label, onSelect, onExpand, handle }: {
  nodes: KgNode[]; edges: KgEdge[]; selectedId: string | null; markedIds?: ReadonlySet<string>; label: string
  onSelect: (id: string | null) => void; onExpand: (id: string) => void; handle?: Ref<GraphCanvasHandle>
}) {
  const host = useRef<HTMLDivElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const sim = useRef<Simulation<SimNode, SimLink> | null>(null)
  const simNodes = useRef<Map<string, SimNode>>(new Map())
  const links = useRef<SimLink[]>([])
  const camera = useRef<Camera>({ x: 0, y: 0, k: 1 })
  const size = useRef({ w: 0, h: 0, dpr: 1 })
  const hover = useRef<string | null>(null)
  const selected = useRef<string | null>(selectedId)
  const marked = useRef<ReadonlySet<string> | undefined>(markedIds)
  const colors = useRef<Record<string, string>>({})
  const frame = useRef(0)
  const needsFit = useRef(true)
  const callbacks = useRef({ onSelect, onExpand })
  callbacks.current = { onSelect, onExpand }
  selected.current = selectedId
  marked.current = markedIds

  const readColors = useCallback(() => {
    if (!host.current) return
    const style = getComputedStyle(host.current)
    const read = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback
    colors.current = {
      structure: read(groupToken.structure, '#2c412b'), space: read(groupToken.space, '#3a89de'), element: read(groupToken.element, '#8a8a8a'), service: read(groupToken.service, '#c98137'), issue: read(groupToken.issue, '#b14142'),
      edge: read('--neutral-350', '#c4c4c4'), edgeStrong: read('--neutral-500', '#8a8a8a'), differs: read('--brick-500', '#cb5454'), text: read('--foreground', '#1a1a1a'), halo: read('--background', '#fdfdfd'), ring: read('--foreground', '#1a1a1a'),
      mark: read('--amber-500', '#e5a648'), font: style.fontFamily || 'sans-serif',
    }
  }, [])

  const draw = useCallback(() => {
    frame.current = 0
    const el = canvas.current; const ctx = el?.getContext('2d')
    if (!el || !ctx) return
    const { w, h, dpr } = size.current; const cam = camera.current; const c = colors.current
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, w, h)
    ctx.setTransform(dpr * cam.k, 0, 0, dpr * cam.k, dpr * cam.x, dpr * cam.y)
    const focusId = hover.current ?? selected.current
    const active = new Set<string>()
    if (focusId) { active.add(focusId); for (const link of links.current) { const s = (link.source as SimNode).id; const t = (link.target as SimNode).id; if (s === focusId) active.add(t); else if (t === focusId) active.add(s) } }
    const dimming = !!focusId
    const markSet = marked.current
    // Edges: solid when confident, dashed when an estimate.
    for (const link of links.current) {
      const s = link.source as SimNode; const t = link.target as SimNode
      if (s.x == null || t.x == null || s.y == null || t.y == null) continue
      const lit = !dimming || (active.has(s.id) && active.has(t.id) && (s.id === focusId || t.id === focusId))
      const estimate = isEstimate(link.edge)
      ctx.globalAlpha = lit ? (dimming ? 0.85 : estimate ? 0.55 : 0.5) : 0.07
      ctx.strokeStyle = link.edge.kind === 'differs' ? c.differs : lit && dimming ? c.edgeStrong : c.edge
      ctx.lineWidth = (lit && dimming ? 1.6 : 1) / Math.sqrt(cam.k)
      ctx.setLineDash(estimate ? [4 / cam.k, 3 / cam.k] : [])
      ctx.beginPath(); ctx.moveTo(s.x, s.y); ctx.lineTo(t.x, t.y); ctx.stroke()
    }
    ctx.setLineDash([])
    // Nodes.
    for (const node of simNodes.current.values()) {
      if (node.x == null || node.y == null) continue
      const lit = !dimming || active.has(node.id)
      ctx.globalAlpha = lit ? 1 : 0.14
      ctx.fillStyle = c[node.group]
      ctx.beginPath(); ctx.arc(node.x, node.y, node.r, 0, Math.PI * 2); ctx.fill()
      ctx.lineWidth = 1.5 / cam.k; ctx.strokeStyle = c.halo; ctx.stroke()
      if (markSet?.has(node.id)) { ctx.lineWidth = 2 / cam.k; ctx.strokeStyle = c.mark; ctx.beginPath(); ctx.arc(node.x, node.y, node.r + 3 / cam.k, 0, Math.PI * 2); ctx.stroke() }
      if (node.id === selected.current) { ctx.lineWidth = 2 / cam.k; ctx.strokeStyle = c.ring; ctx.beginPath(); ctx.arc(node.x, node.y, node.r + 3 / cam.k, 0, Math.PI * 2); ctx.stroke() }
    }
    // Labels: hubs always, the focused neighbourhood, and everything once zoomed in.
    ctx.globalAlpha = 1
    ctx.font = `${12 / cam.k}px ${c.font}`; ctx.textAlign = 'center'; ctx.textBaseline = 'top'; ctx.lineJoin = 'round'
    for (const node of simNodes.current.values()) {
      if (node.x == null || node.y == null) continue
      const show = dimming ? active.has(node.id) : node.hub || cam.k >= 1.7 || !!markSet?.has(node.id)
      if (!show) continue
      const text = node.label.length > 28 ? `${node.label.slice(0, 27)}…` : node.label
      const y = node.y + node.r + 3 / cam.k
      ctx.lineWidth = 3 / cam.k; ctx.strokeStyle = c.halo; ctx.strokeText(text, node.x, y)
      ctx.fillStyle = c.text; ctx.fillText(text, node.x, y)
    }
  }, [])

  const schedule = useCallback(() => { if (!frame.current) frame.current = requestAnimationFrame(draw) }, [draw])

  const fit = useCallback((ids?: string[]) => {
    const { w, h } = size.current
    const list = [...simNodes.current.values()].filter((node) => node.x != null && node.y != null && (!ids?.length || ids.includes(node.id)))
    if (!list.length || !w || !h) return
    let x0 = Infinity; let y0 = Infinity; let x1 = -Infinity; let y1 = -Infinity
    for (const node of list) { x0 = Math.min(x0, node.x! - node.r); x1 = Math.max(x1, node.x! + node.r); y0 = Math.min(y0, node.y! - node.r); y1 = Math.max(y1, node.y! + node.r) }
    const pad = 48
    const k = Math.min(2.2, Math.max(0.15, Math.min((w - pad * 2) / Math.max(1, x1 - x0), (h - pad * 2) / Math.max(1, y1 - y0))))
    camera.current = { k, x: w / 2 - ((x0 + x1) / 2) * k, y: h / 2 - ((y0 + y1) / 2) * k }
    schedule()
  }, [schedule])
  const zoomBy = useCallback((factor: number, at?: { x: number; y: number }) => {
    const cam = camera.current; const { w, h } = size.current
    const px = at?.x ?? w / 2; const py = at?.y ?? h / 2
    const k = Math.min(6, Math.max(0.1, cam.k * factor))
    camera.current = { k, x: px - ((px - cam.x) / cam.k) * k, y: py - ((py - cam.y) / cam.k) * k }
    schedule()
  }, [schedule])
  useImperativeHandle(handle, () => ({ fit, zoomBy: (factor: number) => zoomBy(factor) }), [fit, zoomBy])

  // One simulation for the life of the component.
  useEffect(() => {
    const simulation = forceSimulation<SimNode>([]).alphaDecay(0.035).velocityDecay(0.38)
      .force('charge', forceManyBody<SimNode>().strength(-95).distanceMax(380))
      .force('collide', forceCollide<SimNode>().radius((node) => node.r + 4))
      .force('x', forceX<SimNode>(0).strength(0.035)).force('y', forceY<SimNode>(0).strength(0.035))
      .force('center', forceCenter(0, 0))
      .on('tick', schedule)
      .on('end', () => { if (needsFit.current) { needsFit.current = false; fit() } })
    sim.current = simulation
    return () => { simulation.stop(); cancelAnimationFrame(frame.current); frame.current = 0 }
  }, [fit, schedule])

  // Data changes: keep positions of what was already there, drop new items next to a neighbour.
  const dataKey = useRef('')
  useEffect(() => {
    const simulation = sim.current
    if (!simulation) return
    readColors()
    const deg = degrees(nodes, edges)
    const previous = simNodes.current
    const next = new Map<string, SimNode>()
    const anchors = new Map<string, string>()
    for (const edge of edges) { if (!anchors.has(edge.from)) anchors.set(edge.from, edge.to); if (!anchors.has(edge.to)) anchors.set(edge.to, edge.from) }
    let fresh = 0
    for (const node of nodes) {
      const old = previous.get(node.id)
      const degree = node.degree ?? deg.get(node.id) ?? 0
      const r = nodeRadius(Math.max(degree, deg.get(node.id) ?? 0), node.kind)
      const hub = node.kind === 'project' || node.kind === 'doc' || node.kind === 'level'
      if (old) { old.r = r; old.hub = hub; old.label = node.label; next.set(node.id, old); continue }
      const anchor = previous.get(anchors.get(node.id) ?? '') ?? next.get(anchors.get(node.id) ?? '')
      const angle = (fresh++ * 2.399963) % (Math.PI * 2)
      next.set(node.id, { id: node.id, kind: node.kind, label: node.label, r, hub, group: kindGroup(node.kind), x: (anchor?.x ?? 0) + Math.cos(angle) * 30, y: (anchor?.y ?? 0) + Math.sin(angle) * 30 })
    }
    simNodes.current = next
    links.current = edges.filter((edge) => next.has(edge.from) && next.has(edge.to)).map((edge) => ({ source: next.get(edge.from)!, target: next.get(edge.to)!, edge }))
    simulation.nodes([...next.values()])
    simulation.force('link', forceLink<SimNode, SimLink>(links.current).distance((link) => (link.edge.kind === 'same_as' ? 70 : link.edge.kind === 'contains' || link.edge.kind === 'on_level' ? 52 : 40)).strength((link) => (isEstimate(link.edge) ? 0.25 : 0.55)))
    const key = nodes.map((node) => node.id).sort().join('|')
    const replaced = !previous.size || ![...previous.keys()].some((id) => next.has(id))
    const reduced = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches
    if (replaced) {
      needsFit.current = true
      simulation.alpha(1)
      simulation.tick(reduced ? 300 : 90)
      fit()
    }
    if (key !== dataKey.current) { dataKey.current = key; simulation.alpha(replaced ? 0.5 : 0.6); if (reduced) { simulation.tick(120); simulation.stop() } else simulation.restart() }
    schedule()
  }, [nodes, edges, fit, readColors, schedule])

  useEffect(() => { schedule() }, [selectedId, markedIds, schedule])

  // Size and pixel ratio.
  useEffect(() => {
    const el = host.current; const cv = canvas.current
    if (!el || !cv) return
    const apply = () => {
      const { width, height } = el.getBoundingClientRect()
      const dpr = Math.min(2, window.devicePixelRatio || 1)
      const first = !size.current.w
      size.current = { w: width, h: height, dpr }
      cv.width = Math.max(1, Math.round(width * dpr)); cv.height = Math.max(1, Math.round(height * dpr))
      if (first && width) fit()
      schedule()
    }
    apply()
    const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(apply) : null
    observer?.observe(el)
    return () => observer?.disconnect()
  }, [fit, schedule])

  // Pointer: hover, select, drag a node, pan the background, wheel zoom.
  useEffect(() => {
    const cv = canvas.current
    if (!cv) return
    const toGraph = (event: { clientX: number; clientY: number }) => { const rect = cv.getBoundingClientRect(); const cam = camera.current; return { x: (event.clientX - rect.left - cam.x) / cam.k, y: (event.clientY - rect.top - cam.y) / cam.k, sx: event.clientX - rect.left, sy: event.clientY - rect.top } }
    const hit = (event: { clientX: number; clientY: number }) => {
      const p = toGraph(event); let best: SimNode | null = null; let bestDistance = Infinity
      for (const node of simNodes.current.values()) {
        if (node.x == null || node.y == null) continue
        const d = Math.hypot(node.x - p.x, node.y - p.y); const reach = node.r + 4 / camera.current.k
        if (d <= reach && d < bestDistance) { best = node; bestDistance = d }
      }
      return best
    }
    let drag: { node: SimNode | null; startX: number; startY: number; camX: number; camY: number; moved: boolean; pointer: number } | null = null
    const down = (event: PointerEvent) => {
      if (event.button !== 0) return
      const node = hit(event)
      drag = { node, startX: event.clientX, startY: event.clientY, camX: camera.current.x, camY: camera.current.y, moved: false, pointer: event.pointerId }
      cv.setPointerCapture(event.pointerId)
      if (node) { node.fx = node.x; node.fy = node.y }
    }
    const move = (event: PointerEvent) => {
      if (!drag) { const node = hit(event); const id = node?.id ?? null; if (id !== hover.current) { hover.current = id; cv.style.cursor = id ? 'pointer' : 'grab'; schedule() } return }
      const dx = event.clientX - drag.startX; const dy = event.clientY - drag.startY
      if (!drag.moved && Math.hypot(dx, dy) > 4) { drag.moved = true; if (drag.node) sim.current?.alphaTarget(0.25).restart() }
      if (!drag.moved) return
      if (drag.node) { const p = toGraph(event); drag.node.fx = p.x; drag.node.fy = p.y } else { camera.current = { ...camera.current, x: drag.camX + dx, y: drag.camY + dy }; cv.style.cursor = 'grabbing'; schedule() }
    }
    const up = (event: PointerEvent) => {
      if (!drag) return
      const finished = drag; drag = null
      if (cv.hasPointerCapture(finished.pointer)) cv.releasePointerCapture(finished.pointer)
      if (finished.node) { finished.node.fx = null; finished.node.fy = null; sim.current?.alphaTarget(0) }
      cv.style.cursor = hover.current ? 'pointer' : 'grab'
      if (!finished.moved) callbacks.current.onSelect(finished.node?.id ?? null)
      void event
    }
    const leave = () => { if (!drag && hover.current) { hover.current = null; schedule() } }
    const wheel = (event: WheelEvent) => { event.preventDefault(); const p = toGraph(event); zoomBy(Math.exp(-event.deltaY * (event.ctrlKey ? 0.01 : 0.0015)), { x: p.sx, y: p.sy }) }
    const dbl = (event: MouseEvent) => { const node = hit(event); if (node) callbacks.current.onExpand(node.id) }
    cv.style.cursor = 'grab'
    cv.addEventListener('pointerdown', down); cv.addEventListener('pointermove', move); cv.addEventListener('pointerup', up); cv.addEventListener('pointercancel', up)
    cv.addEventListener('pointerleave', leave); cv.addEventListener('wheel', wheel, { passive: false }); cv.addEventListener('dblclick', dbl)
    return () => {
      cv.removeEventListener('pointerdown', down); cv.removeEventListener('pointermove', move); cv.removeEventListener('pointerup', up); cv.removeEventListener('pointercancel', up)
      cv.removeEventListener('pointerleave', leave); cv.removeEventListener('wheel', wheel); cv.removeEventListener('dblclick', dbl)
    }
  }, [schedule, zoomBy])

  return <div className="kg-canvas" ref={host}>
    <canvas ref={canvas} role="img" aria-label={label} data-testid="kg-canvas" />
    <div className="kg-zoom" role="group" aria-label="Zoom">
      <Button variant="outline" size="icon-sm" aria-label="Zoom in" onClick={() => zoomBy(1.4)}><Plus size={16} /></Button>
      <Button variant="outline" size="icon-sm" aria-label="Zoom out" onClick={() => zoomBy(1 / 1.4)}><Minus size={16} /></Button>
      <Button variant="outline" size="icon-sm" aria-label="Fit to view" onClick={() => fit()}><Maximize2 size={15} /></Button>
    </div>
  </div>
}
