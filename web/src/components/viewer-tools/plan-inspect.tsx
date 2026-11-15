/** Click-to-inspect for the Data page's plain 2D page view: an SVG over the page image (same aspect fit as the
 * image's object-fit: contain) that picks the plan-map item under the pointer, outlines it, shows a one-line
 * summary on hover and opens the deterministic item panel on click. Also hosts the layers overlay and the
 * measuring tool. Plain code over planmap-<page>.json; no model call, no 3D render. */
import { useEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent } from 'react'
import { Ruler } from 'lucide-react'
import { workspaceApi } from '../../lib/api'
import { pickPlanItem, type PlanPickItem } from '../../lib/pick-item'
import { kindFromItemId, kindStyle } from '../../lib/kind-colors'
import { planItemSummary } from '../../lib/plan-item-summary'
import { snapPoint, formatM, formatM2, type Pt } from '../../lib/measure'
import { MeasureLayer, useMeasure } from './measure-layer'
import { PlanLayerChips, PlanLayerShapes, usePlanLayers } from './plan-layers'
import { PlanHoverTip } from './plan-hover-tip'
import { Button } from '../ui'
import './plan-inspect.css'

export type InspectItem = PlanPickItem & { label?: string | null; props?: Record<string, unknown> | null }

export function usePlanInspect(docId: string, page: number) {
  const [items, setItems] = useState<InspectItem[]>([])
  const [mPerPx, setMPerPx] = useState<number | null>(null)
  const [hover, setHover] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const layers = usePlanLayers()
  const measure = useMeasure(mPerPx)
  useEffect(() => {
    const controller = new AbortController()
    setItems([]); setMPerPx(null); setHover(null); setSelected(null)
    workspaceApi.getPlanMap(docId, page, controller.signal).then((pm) => {
      if (controller.signal.aborted) return
      setMPerPx(typeof pm.scale?.m_per_px === 'number' && pm.scale.m_per_px > 0 ? pm.scale.m_per_px : null)
      setItems((pm.items ?? []).flatMap((item) => item.bbox_px ? [{
        id: item.item_id, kind: item.kind ?? kindFromItemId(item.item_id) ?? 'other', bbox: item.bbox_px, polygon: item.polygon_px ?? null,
        role: typeof item.props?.role === 'string' ? item.props.role : null, label: item.label ?? null, props: item.props ?? null,
      }] : []))
    }).catch(() => {})
    return () => controller.abort()
  }, [docId, page])
  // Keyboard while measuring (capture phase, so the page's own Escape handling does not also close the document):
  // Esc cancels the measurement (distance or area), Enter closes an area, Backspace removes the last point.
  useEffect(() => {
    if (!measure.mode) return
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); measure.stop() }
      else if (event.key === 'Enter' && measure.mode === 'area') { event.preventDefault(); event.stopPropagation(); measure.close() }
      else if (event.key === 'Backspace' && !(event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement)) { event.preventDefault(); measure.undo() }
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [measure.mode, measure.stop, measure.close, measure.undo]) // eslint-disable-line react-hooks/exhaustive-deps
  const byId = useMemo(() => new Map(items.map((item) => [item.id, item])), [items])
  return { docId, page, items, byId, mPerPx, hover, setHover, selected, setSelected, layers, measure }
}
export type PlanInspect = ReturnType<typeof usePlanInspect>

/** Toolbar part: layer chips, the ruler toggle and the measuring readout. Renders nothing when the page has no plan map. */
export function PlanInspectTools({ state }: { state: PlanInspect }) {
  const { items, layers, measure, mPerPx } = state
  if (!items.length) return null
  return <div className="plan-inspect-tools">
    <PlanLayerChips items={items} shown={layers.shown} onToggle={layers.toggle} />
    <Button variant="ghost" size="icon-xs" aria-label="Measure distance on the drawing" aria-pressed={!!measure.mode}
      title={mPerPx ? 'Measure: click two points' : 'Measure (no scale on this drawing)'}
      onClick={() => { if (measure.mode) measure.stop(); else { state.setSelected(null); measure.start('distance') } }}><Ruler size={14} /></Button>
    {measure.mode && <span className="plan-measure-readout" role="status" aria-live="polite">
      {!mPerPx ? 'No scale on this drawing, so distances cannot be measured.'
        : measure.result?.distanceM != null ? `Distance ${formatM(measure.result.distanceM)}`
        : measure.result?.areaM2 != null ? `Area ${formatM2(measure.result.areaM2)} · perimeter ${formatM(measure.result.perimeterM ?? 0)}`
        : measure.mode === 'distance' ? 'Click two points (snaps to plan corners) · Esc to cancel' : 'Click corners, double-click or Enter to close · Esc to cancel'}
      <Button variant="ghost" size="xs" aria-pressed={measure.mode === 'distance'} onClick={() => measure.start('distance')}>Distance</Button>
      <Button variant="ghost" size="xs" aria-pressed={measure.mode === 'area'} onClick={() => measure.start('area')}>Area</Button>
      <Button variant="ghost" size="xs" onClick={measure.stop}>Done</Button>
    </span>}
  </div>
}

/** Overlay part: goes inside the page image's box, sized to the image's natural pixels. */
export function PlanInspectOverlay({ state, image }: { state: PlanInspect; image: { width: number; height: number } }) {
  const { items, byId, mPerPx, hover, setHover, selected, setSelected, layers, measure } = state
  const svg = useRef<SVGSVGElement>(null)
  const [tipAt, setTipAt] = useState<{ x: number; y: number; w: number; h: number } | null>(null)
  const down = useRef<{ x: number; y: number } | null>(null)
  function pagePoint(event: { clientX: number; clientY: number }): Pt | null {
    const el = svg.current, ctm = el?.getScreenCTM()
    if (!el || !ctm) return null
    const p = new DOMPoint(event.clientX, event.clientY).matrixTransform(ctm.inverse())
    return p.x < 0 || p.y < 0 || p.x > image.width || p.y > image.height ? null : [p.x, p.y]
  }
  function unitsPerScreenPx() {
    const ctm = svg.current?.getScreenCTM()
    return ctm && ctm.a > 0 ? 1 / ctm.a : 1
  }
  function pickAt(event: { clientX: number; clientY: number }) {
    const p = pagePoint(event)
    return p ? pickPlanItem(p, items, Math.min(6 * unitsPerScreenPx(), 40)) : null
  }
  function onMove(event: ReactPointerEvent<SVGSVGElement>) {
    if (measure.mode) {
      const p = pagePoint(event)
      measure.move(p ? snapPoint(p, items, 8 * unitsPerScreenPx()) : null)
      return
    }
    const id = pickAt(event)
    if (id !== hover) setHover(id)
    const box = svg.current?.parentElement?.getBoundingClientRect()
    setTipAt(id && box ? { x: event.clientX - box.left, y: event.clientY - box.top, w: box.width, h: box.height } : null)
  }
  function onUp(event: ReactPointerEvent<SVGSVGElement>) {
    const start = down.current
    down.current = null
    if (!start || Math.hypot(event.clientX - start.x, event.clientY - start.y) > 5) return
    if (measure.mode) {
      const p = pagePoint(event)
      if (p) measure.add(snapPoint(p, items, 8 * unitsPerScreenPx()))
      return
    }
    const id = pickAt(event)
    setSelected(id)
  }
  if (!items.length) return null
  const outlined = [...new Set([hover, selected])].flatMap((id) => (id ? [byId.get(id)] : [])).filter((item): item is InspectItem => !!item)
  const tipItem = hover ? byId.get(hover) : undefined
  return <>
    <svg ref={svg} className={`plan-inspect-svg ${hover && !measure.mode ? 'is-pickable' : ''} ${measure.mode ? 'is-measuring' : ''}`}
      viewBox={`0 0 ${image.width} ${image.height}`} preserveAspectRatio="xMidYMid meet" data-testid="plan-inspect"
      aria-label="Plan items. Click an item for its details."
      onPointerDown={(event) => { down.current = { x: event.clientX, y: event.clientY } }}
      onPointerMove={onMove} onPointerUp={onUp}
      onPointerLeave={() => { setHover(null); setTipAt(null); if (measure.mode) measure.move(null) }}
      onDoubleClick={() => { if (measure.mode === 'area') measure.close() }}>
      <PlanLayerShapes items={items} shown={layers.shown} selectedId={selected} />
      {!measure.mode && outlined.map((item) => {
        const [x, y, right, bottom] = item.bbox
        const outline = item.polygon && item.polygon.length >= 3 && item.kind !== 'text'
        return <g key={item.id} className={`plan-pick ${item.id === selected ? 'is-selected' : ''}`} data-testid="plan-pick" data-item-id={item.id} style={{ '--kind-color': kindStyle(item.kind).color } as CSSProperties}>
          {outline ? <polygon points={item.polygon!.map(([px, py]) => `${px},${py}`).join(' ')} vectorEffect="non-scaling-stroke" />
            : <rect x={x} y={y} width={Math.max(0, right - x)} height={Math.max(0, bottom - y)} vectorEffect="non-scaling-stroke" />}
        </g>
      })}
      {measure.mode && <MeasureLayer mode={measure.mode} points={measure.points} cursor={measure.cursor} mPerPx={mPerPx} scale={1 / unitsPerScreenPx()} />}
    </svg>
    {!measure.mode && tipItem && tipAt && <PlanHoverTip text={planItemSummary(tipItem, mPerPx)} x={tipAt.x} y={tipAt.y} containerWidth={tipAt.w} containerHeight={tipAt.h} />}
  </>
}
