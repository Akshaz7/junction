import { useEffect, useId, useRef, useState, type CSSProperties } from 'react'
import { Layers2, X } from 'lucide-react'
import { workspaceApi } from '../lib/api'
import { discipline, rankOverlaySheets, registeredSheet, requestAlignment, type Alignment, type OverlayDoc, type SheetSize, type XY } from '../lib/sheet-overlay'
import { SheetCompare } from './sheet-compare'
import { parseHex, tintMatrix } from '../lib/sheet-compare'
import { Button } from './ui'
import './sheet-overlay.css'

type Images = { base: string; overlay: string }

/** Source-pixel picking, with zoom/pan for dense drawings. No screenshot coordinates enter the fit. */
function PointSheet({ src, size, label, points, onPick, view: externalView, onView }: {
  src: string; size: SheetSize; label: string; points?: XY[]; onPick?: (p: XY) => void
  view?: { x: number; y: number; zoom: number }; onView?: (v: { x: number; y: number; zoom: number }) => void
}) {
  const [localView, setLocalView] = useState({ x: 0, y: 0, zoom: 1 })
  const view = externalView ?? localView, update = onView ?? setLocalView
  const svg = useRef<SVGSVGElement>(null), drag = useRef<{ x: number; y: number; start: XY; moved: boolean } | null>(null)
  function pagePoint(x: number, y: number): XY {
    const p = new DOMPoint(x, y).matrixTransform(svg.current!.getScreenCTM()!.inverse())
    return [p.x, p.y]
  }
  return <div className="overlay-point-sheet"><header>{label}<span />
    <Button variant="ghost" size="xs" aria-label={`Zoom out ${label}`} onClick={() => update({ ...view, zoom: Math.max(1, view.zoom/1.5) })}>−</Button>
    <Button variant="ghost" size="xs" aria-label={`Zoom in ${label}`} onClick={() => update({ ...view, zoom: Math.min(20, view.zoom*1.5) })}>+</Button>
    <Button variant="ghost" size="xs" onClick={() => update({ x: 0, y: 0, zoom: 1 })}>Fit</Button>
  </header><svg ref={svg} viewBox={`${view.x*size.w} ${view.y*size.h} ${size.w/view.zoom} ${size.h/view.zoom}`} role="img" aria-label={label}
    onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); drag.current = { x: e.clientX, y: e.clientY, start: pagePoint(e.clientX, e.clientY), moved: false } }}
    onPointerMove={(e) => {
      const d = drag.current; if (!d) return
      if (Math.hypot(e.clientX-d.x, e.clientY-d.y) > 5) d.moved = true
      if (d.moved) { const p = pagePoint(e.clientX, e.clientY); update({ ...view, x: view.x+(d.start[0]-p[0])/size.w, y: view.y+(d.start[1]-p[1])/size.h }) }
    }}
    onPointerUp={(e) => { const d = drag.current; drag.current = null; if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId)
      if (d && !d.moved && onPick) { const p = pagePoint(e.clientX, e.clientY); if (p[0]>=0 && p[1]>=0 && p[0]<=size.w && p[1]<=size.h) onPick(p) } }}
    onPointerCancel={() => { drag.current = null }}>
    <image href={src} width={size.w} height={size.h} />
    {points?.map(([x,y], i) => <g key={i} transform={`translate(${x} ${y})`}><circle r={size.w/(80*view.zoom)} fill="var(--blue-600)" stroke="#fff" strokeWidth={size.w/(700*view.zoom)} /><text textAnchor="middle" dominantBaseline="central" fill="#fff" fontSize={size.w/(80*view.zoom)}>{i+1}</text></g>)}
  </svg></div>
}

export function SheetOverlay({ baseDocId, page = 1, initialOverlayDocId, onClose, onAlignment }: {
  onAlignment?: (result: Alignment, base: OverlayDoc, overlay: OverlayDoc, basePage: number, overlayPage: number) => void
  baseDocId: string; page?: number; initialOverlayDocId?: string | null; onClose: () => void
}) {
  const [docs, setDocs] = useState<OverlayDoc[]>([]), [overlayId, setOverlayId] = useState(initialOverlayDocId ?? '')
  const [basePage, setBasePage] = useState(page), [otherPage, setOtherPage] = useState(1)
  const [images, setImages] = useState<Images | null>(null), [result, setResult] = useState<Alignment | null>(null)
  const [registered, setRegistered] = useState(''), [error, setError] = useState(''), [busy, setBusy] = useState(false), [retry, setRetry] = useState(0)
  const [manual, setManual] = useState(false), [basePoints, setBasePoints] = useState<XY[]>([]), [overlayPoints, setOverlayPoints] = useState<XY[]>([])
  const [baseVisible, setBaseVisible] = useState(true), [otherVisible, setOtherVisible] = useState(true), [side, setSide] = useState(false)
  const [sideView, setSideView] = useState({ x: 0, y: 0, zoom: 1 })
  const id = useId().replace(/:/g, ''), heading = useRef<HTMLHeadingElement>(null)
  const alignmentCallback = useRef(onAlignment); alignmentCallback.current = onAlignment
  const base = docs.find((d) => d.doc_id === baseDocId), overlay = docs.find((d) => d.doc_id === overlayId)
  const options = base ? rankOverlaySheets(base, docs) : []
  const color = overlay ? discipline(overlay).color : '#166ed1'
  useEffect(() => { let active = true; workspaceApi.getDocuments().then((d) => { if (active) setDocs(d) }).catch((e) => { if (active) setError(e.message) }); heading.current?.focus(); return () => { active = false } }, [])
  useEffect(() => {
    setResult(null); setRegistered(''); setImages(null); setManual(false); setBasePoints([]); setOverlayPoints([]); setError(''); setSideView({ x: 0, y: 0, zoom: 1 })
    if (!overlayId) return
    const controller = new AbortController(); const urls: string[] = []
    setBusy(true)
    Promise.all([
      requestAlignment(baseDocId, overlayId, basePage, otherPage, controller.signal),
      workspaceApi.getPageImage(baseDocId, basePage, controller.signal), workspaceApi.getPageImage(overlayId, otherPage, controller.signal),
    ]).then(async ([alignment, a, b]) => {
      if (controller.signal.aborted) return
      const base = URL.createObjectURL(a), overlay = URL.createObjectURL(b); urls.push(base, overlay)
      setImages({ base, overlay }); setResult(alignment)
      if (alignment.matrix) {
        const output = await registeredSheet(overlay, alignment.matrix, alignment.base_image); urls.push(output)
        if (!controller.signal.aborted) setRegistered(output)
        else URL.revokeObjectURL(output)
      }
    }).catch((e) => { if (!controller.signal.aborted) setError(e.message) }).finally(() => { if (!controller.signal.aborted) setBusy(false) })
    return () => { controller.abort(); urls.forEach((url) => URL.revokeObjectURL(url)) }
  }, [baseDocId, overlayId, basePage, otherPage, retry])
  useEffect(() => { if (initialOverlayDocId) setOverlayId(initialOverlayDocId) }, [initialOverlayDocId])
  useEffect(() => {
    if (result && base && overlay) alignmentCallback.current?.(result, base, overlay, basePage, otherPage)
  }, [result, base, overlay, basePage, otherPage])
  const manualController = useRef<AbortController | null>(null)
  useEffect(() => () => manualController.current?.abort(), [overlayId, basePage, otherPage])
  async function saveManual() {
    if (!images || !result) return
    manualController.current?.abort(); const controller = new AbortController(); manualController.current = controller
    setBusy(true); setError('')
    try {
      const alignment = await requestAlignment(baseDocId, overlayId, basePage, otherPage, controller.signal, { base: basePoints, overlay: overlayPoints })
      const url = await registeredSheet(images.overlay, alignment.matrix!, alignment.base_image)
      if (controller.signal.aborted) { URL.revokeObjectURL(url); return }
      setRegistered((old) => { if (old) URL.revokeObjectURL(old); return url }); setResult(alignment); setManual(false)
    } catch (e) { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'Choose two different points.') }
    finally { if (!controller.signal.aborted) setBusy(false) }
  }
  // Manual registrations are session state only; page/pair changes always reset them.
  const registeredRef = useRef(registered); registeredRef.current = registered
  useEffect(() => () => { if (registeredRef.current) URL.revokeObjectURL(registeredRef.current) }, [])
  return <section className="sheet-overlay" aria-labelledby={`${id}-title`} onKeyDown={(e) => { if (e.key === 'Escape') { e.stopPropagation(); onClose() } }}>
    <header className="overlay-heading"><Layers2 size={18} /><h3 ref={heading} tabIndex={-1} id={`${id}-title`}>Overlay sheets</h3><Button variant="ghost" size="icon" aria-label="Close overlay" onClick={onClose}><X size={18} /></Button></header>
    <div className="overlay-pickers"><label>Base sheet<strong>{base?.title || 'Current sheet'}</strong></label>
      <label>Page<input aria-label="Base page" type="number" min={1} max={base?.pages ?? 1} value={basePage} onChange={(e) => setBasePage(Math.max(1, Math.min(base?.pages ?? 1, Number(e.target.value) || 1)))} /></label>
      <label>Overlay with…<select aria-label="Overlay sheet" value={overlayId} onChange={(e) => { setOverlayId(e.target.value); setOtherPage(1) }}><option value="">Choose a sheet</option>{options.map((d) => <option key={d.doc_id} value={d.doc_id}>{d.title}{d.project ? ` · ${d.project}` : ''}{d.floor || d.storey ? ` · ${d.floor || d.storey}` : ''}</option>)}</select></label>
      <label>Page<input aria-label="Overlay page" type="number" min={1} max={overlay?.pages ?? 1} value={otherPage} onChange={(e) => setOtherPage(Math.max(1, Math.min(overlay?.pages ?? 1, Number(e.target.value) || 1)))} /></label>
    </div>
    {!overlayId && <p className="overlay-note" role="status">Choose another discipline’s sheet of the same floor. Sheets from the same project and floor appear first when that information is available.</p>}
    {error && <p className="overlay-error" role="alert">{error} <Button size="xs" onClick={() => setRetry(retry+1)}>Try again</Button></p>}
    {busy && <p className="overlay-note" role="status">Checking shared drawing anchors…</p>}
    {result && <><p className="overlay-status" role="status" data-testid="alignment-status">{result.detail}</p>
      <div className="overlay-controls"><label><input type="checkbox" checked={baseVisible} onChange={(e) => setBaseVisible(e.target.checked)} />Base · grey</label><label style={{ color }}><input type="checkbox" checked={otherVisible} onChange={(e) => setOtherVisible(e.target.checked)} />{overlay ? discipline(overlay).name : 'Overlay'}</label>
        <Button size="xs" variant="ghost" aria-pressed={side} onClick={() => setSide(!side)}>Side by side</Button>
        <Button size="xs" variant="ghost" onClick={() => { setManual(true); setBasePoints([]); setOverlayPoints([]) }}>Align with two points</Button></div>
      {manual && images ? <><p className="overlay-note">Click the same two grid crossings on each sheet, in the same order. Choose crossings far apart. Zoom and drag to place them precisely.</p><div className="overlay-two-sheets">
        <PointSheet key={`base-${overlayId}`} src={images.base} size={result.base_image} label="Base alignment points" points={basePoints} onPick={(p) => setBasePoints((old) => old.length < 2 ? [...old, p] : old)} />
        <PointSheet key={`other-${overlayId}`} src={images.overlay} size={result.overlay_image} label="Overlay alignment points" points={overlayPoints} onPick={(p) => setOverlayPoints((old) => old.length < 2 ? [...old, p] : old)} />
      </div><div className="overlay-controls"><span>{basePoints.length}/2 base · {overlayPoints.length}/2 overlay</span><Button size="sm" disabled={busy || basePoints.length !== 2 || overlayPoints.length !== 2} onClick={() => void saveManual()}>Apply alignment</Button><Button size="sm" variant="ghost" onClick={() => setManual(false)}>Cancel</Button></div></>
      : registered && images ? side ? <div className="overlay-two-sheets" aria-label="Sheets with linked zoom and pan">
        <PointSheet src={baseVisible ? images.base : ''} size={result.base_image} label={base?.title || 'Base sheet'} view={sideView} onView={setSideView} />
        <PointSheet src={otherVisible ? registered : ''} size={result.base_image} label={overlay?.title || 'Overlay sheet'} view={sideView} onView={setSideView} />
      </div> : <div className="overlay-compare" data-base-visible={baseVisible} data-overlay-visible={otherVisible} style={{ '--discipline-filter': `url(#${id}-tint)` } as CSSProperties}>
        <svg width="0" height="0" aria-hidden><defs><filter id={`${id}-tint`} colorInterpolationFilters="sRGB"><feColorMatrix type="matrix" values={tintMatrix(parseHex(color, [0, .4, .8]))} /></filter></defs></svg>
        <SheetCompare key={`${overlayId}-${basePage}-${otherPage}-${registered}`} prev={{ label: base?.title || 'Base sheet', src: images.base }} curr={{ label: overlay?.title || 'Overlay sheet', src: registered }} size={result.base_image} changes={[]} initialMode="Overlay" showHint={false} emptyText="This view compares disciplines. It does not infer changes or clashes." />
      </div> : images && !busy && <div className="overlay-two-sheets"><PointSheet src={images.base} size={result.base_image} label="Base sheet" /><PointSheet src={images.overlay} size={result.overlay_image} label="Overlay sheet" /></div>}
      <p className="overlay-footnote">{result.status === 'manual' ? 'Manual fit: check a third crossing.' : 'Residual measures agreement between anchors; check the drawing before ordering material.'} Both layers share zoom and pan in the comparison.</p>
    </>}
  </section>
}
