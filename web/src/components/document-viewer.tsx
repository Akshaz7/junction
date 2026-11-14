import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { ChevronDown, ChevronLeft, ChevronRight, Download, FileSymlink, FileText, Highlighter, Maximize2, Minus, PenLine, Plus, Search, X } from 'lucide-react'
import { workspaceApi } from '../lib/api'
import type { Answer, Citation, Document } from '../lib/types'
import { fitPage, focusBox, zoomAt, type PageTransform, type Point, type Size } from '../lib/page-transform'
import { viewerEvidence } from '../lib/viewer-evidence'
import { Button } from './ui'
import { VisualiseItButton } from '../viewer3d/VisualiseIt'
import './document-viewer.css'

export function useViewerSheet() {
  const [sheet, setSheet] = useState(() => typeof window !== 'undefined' && window.matchMedia('(max-width: 800px)').matches)
  useEffect(() => {
    const query = window.matchMedia('(max-width: 800px)')
    const update = () => setSheet(query.matches)
    update()
    query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [])
  return sheet
}

export function DocumentViewer({ answer, citation, sheet, onClose }: {
  answer: Answer; citation: Citation; sheet: boolean; onClose: () => void
}) {
  const { regions, initial } = useMemo(() => viewerEvidence(answer, citation), [answer, citation])
  const [active, setActive] = useState(initial)
  const [doc, setDoc] = useState<Document | null>(null)
  const [imageUrl, setImageUrl] = useState('')
  const [image, setImage] = useState<Size | null>(null)
  const [viewport, setViewport] = useState<Size>({ width: 0, height: 0 })
  const [view, setView] = useState<PageTransform>({ x: 0, y: 0, scale: 1 })
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const stage = useRef<HTMLDivElement>(null)
  const panel = useRef<HTMLElement>(null)
  const close = useRef<HTMLButtonElement>(null)
  const pointers = useRef(new Map<number, Point>())
  const returnFocus = useRef(typeof document !== 'undefined' ? document.activeElement as HTMLElement | null : null)

  useEffect(() => {
    const controller = new AbortController()
    let disposed = false
    let url = ''
    setError('')
    setImageUrl('')
    setImage(null)
    // Let StrictMode's setup/cleanup replay finish before starting network requests.
    Promise.resolve()
      .then(async () => {
        if (disposed) return
        // Load credit and image together so an uncredited drawing is never displayed.
        const [metadata, blob] = await Promise.all([
          workspaceApi.getDocument(citation.doc_id),
          workspaceApi.getPageImage(citation.doc_id, citation.page, controller.signal),
        ])
        if (disposed) return
        url = URL.createObjectURL(blob)
        setDoc(metadata)
        setImageUrl(url)
      }).catch((err: unknown) => {
        if (!disposed) setError(err instanceof Error ? err.message : 'The drawing could not be loaded.')
      })
    return () => { disposed = true; controller.abort(); if (url) URL.revokeObjectURL(url) }
  }, [citation.doc_id, citation.page, retry])

  useLayoutEffect(() => {
    const node = stage.current
    if (!node) return
    const observer = new ResizeObserver(() => setViewport({ width: node.clientWidth, height: node.clientHeight }))
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    if (!image || !viewport.width || !viewport.height) return
    const fitted = fitPage(image, viewport)
    setView(regions[active] ? focusBox(regions[active].bbox, viewport, fitted.scale) : fitted)
  }, [image, viewport, active, regions])

  useEffect(() => {
    if (sheet) close.current?.focus()
  }, [sheet])
  useEffect(() => {
    const trigger = returnFocus.current
    return () => { if (trigger?.isConnected) trigger.focus() }
  }, [])

  const fittedScale = image ? fitPage(image, viewport).scale : 1
  const minScale = fittedScale / 4
  const maxScale = Math.max(8, fittedScale * 16)
  function limitScale(scale: number) { return Math.min(maxScale, Math.max(minScale, scale)) }
  function zoom(factor: number, anchor = { x: viewport.width / 2, y: viewport.height / 2 }) {
    setView((previous) => zoomAt(previous, anchor, limitScale(previous.scale * factor)))
  }
  useEffect(() => {
    const node = stage.current
    if (!node) return
    const wheel = (event: WheelEvent) => {
      event.preventDefault()
      const rect = node.getBoundingClientRect()
      setView((previous) => zoomAt(previous, { x: event.clientX - rect.left, y: event.clientY - rect.top },
        Math.min(maxScale, Math.max(minScale, previous.scale * Math.exp(-event.deltaY * 0.002)))))
    }
    node.addEventListener('wheel', wheel, { passive: false })
    return () => node.removeEventListener('wheel', wheel)
  }, [minScale, maxScale])

  function pointerPoint(clientX: number, clientY: number): Point {
    const rect = stage.current!.getBoundingClientRect()
    return { x: clientX - rect.left, y: clientY - rect.top }
  }
  function midpoint(points: Point[]): Point {
    return { x: (points[0].x + points[1].x) / 2, y: (points[0].y + points[1].y) / 2 }
  }
  function distance(points: Point[]) { return Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y) }

  return <aside ref={panel} className={`document-viewer ${sheet ? 'viewer-sheet' : ''}`} role={sheet ? 'dialog' : 'region'} aria-modal={sheet || undefined} aria-label="Drawing viewer"
    onKeyDown={(event) => {
      // The 3D viewer owns keyboard handling while its native modal is open.
      if ((event.target as HTMLElement).closest('dialog')) return
      if (event.key === 'Escape') { event.stopPropagation(); onClose() }
      if (sheet && event.key === 'Tab') {
        const controls = panel.current?.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], [tabindex="0"]')
        if (!controls?.length) return
        const first = controls[0], last = controls[controls.length - 1]
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
        if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
      }
    }}>
    <header className="viewer-heading"><FileText size={24} /><div><strong>{doc?.title ?? citation.doc_id}</strong><small>/{doc?.source || 'Drawings'}</small></div>
      <div className="viewer-source-nav">
        <a className="viewer-open-source" aria-label="Open source page" href={imageUrl || undefined} target="_blank" rel="noreferrer"><FileSymlink size={16} /></a>
        <Button variant="ghost" size="icon" aria-label="Previous source" disabled={!image || active <= 0} onClick={() => setActive(active - 1)}><ChevronLeft size={16} /></Button>
        <span aria-live="polite" data-testid="source-position">{regions.length ? active + 1 : 0} of {regions.length}</span>
        <ChevronDown className="viewer-source-chevron" size={14} aria-hidden="true" />
        <Button variant="ghost" size="icon" aria-label="Next source" disabled={!image || active >= regions.length - 1} onClick={() => setActive(active + 1)}><ChevronRight size={16} /></Button>
        <Button className="viewer-fit" variant="ghost" size="icon" aria-label="Fit drawing" disabled={!image} onClick={() => image && setView(fitPage(image, viewport))}><Maximize2 size={16} /></Button>
      </div>
      <button ref={close} type="button" className="button button-ghost button-size-icon" aria-label="Close drawing viewer" onClick={onClose}><X size={18} /></button>
    </header>
    <div className="viewer-toolbar" aria-label="Drawing controls">
      <div className="viewer-page-position"><ChevronLeft size={14} /><span className="page-number">{citation.page}</span><span>/ {doc?.pages ?? '…'}</span><ChevronRight size={14} /></div>
      <span className="toolbar-spacer" />
      <span className="viewer-markup-tools" aria-hidden="true"><Search size={16} /><Highlighter size={16} /><PenLine size={16} /></span>
      <a className="viewer-download" aria-label="Download drawing page" href={imageUrl || undefined} download={`${doc?.title ?? citation.doc_id}-page-${citation.page}.png`}><Download size={16} /></a>
      <span className="viewer-toolbar-divider" />
      <div className="viewer-zoom-controls">
        <Button variant="ghost" size="icon" aria-label="Zoom out" disabled={!image} onClick={() => zoom(1 / 1.25)}><Minus size={16} /></Button>
        <span aria-label="Zoom level">{Math.round(view.scale / fittedScale * 100)}%</span>
        <Button variant="ghost" size="icon" aria-label="Zoom in" disabled={!image} onClick={() => zoom(1.25)}><Plus size={16} /></Button>
      </div>
    </div>
    <div className="drawing-stage" ref={stage} data-testid="drawing-viewport" tabIndex={0} aria-label="Drawing canvas. Drag to pan, scroll or pinch to zoom. Arrow keys pan, plus and minus zoom, zero fits."
      onKeyDown={(event) => {
        if (event.target !== event.currentTarget) return
        const moves: Record<string, Point> = { ArrowLeft: { x: 40, y: 0 }, ArrowRight: { x: -40, y: 0 }, ArrowUp: { x: 0, y: 40 }, ArrowDown: { x: 0, y: -40 } }
        if (moves[event.key]) { event.preventDefault(); const delta = moves[event.key]; setView((previous) => ({ ...previous, x: previous.x + delta.x, y: previous.y + delta.y })) }
        if (event.key === '+' || event.key === '=') { event.preventDefault(); zoom(1.25) }
        if (event.key === '-') { event.preventDefault(); zoom(1 / 1.25) }
        if (event.key === '0' && image) { event.preventDefault(); setView(fitPage(image, viewport)) }
      }}
      onDoubleClick={(event) => zoom(2, pointerPoint(event.clientX, event.clientY))}
      onPointerDown={(event) => {
        if (!image || (event.pointerType === 'mouse' && event.button !== 0)) return
        event.currentTarget.setPointerCapture(event.pointerId)
        pointers.current.set(event.pointerId, pointerPoint(event.clientX, event.clientY))
      }}
      onPointerMove={(event) => {
        if (!pointers.current.has(event.pointerId)) return
        const before = [...pointers.current.values()]
        const old = pointers.current.get(event.pointerId)!
        const point = pointerPoint(event.clientX, event.clientY)
        pointers.current.set(event.pointerId, point)
        const after = [...pointers.current.values()]
        setView((previous) => {
          if (before.length === 2) {
            const a = midpoint(before), b = midpoint(after)
            const scaled = zoomAt(previous, a, limitScale(previous.scale * distance(after) / Math.max(1, distance(before))))
            return { ...scaled, x: scaled.x + b.x - a.x, y: scaled.y + b.y - a.y }
          }
          return { ...previous, x: previous.x + point.x - old.x, y: previous.y + point.y - old.y }
        })
      }}
      onPointerUp={(event) => pointers.current.delete(event.pointerId)}
      onPointerCancel={(event) => pointers.current.delete(event.pointerId)}
      onLostPointerCapture={(event) => pointers.current.delete(event.pointerId)}>
      {imageUrl && <div className="drawing-plane" style={{ width: image?.width, height: image?.height, transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})`, visibility: image ? 'visible' : 'hidden' }}>
        <img src={imageUrl} alt={`Drawing: ${doc?.title ?? citation.doc_id}, page ${citation.page}`} draggable={false}
          onLoad={(event) => setImage({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })}
          onError={() => { setImage(null); setError('This page image could not be displayed.') }} />
        {image && <svg className="drawing-evidence" width={image.width} height={image.height} viewBox={`0 0 ${image.width} ${image.height}`} aria-label="Numbered drawing evidence">
          {regions.map((region, index) => {
            const [x, y, right, bottom] = region.bbox
            const labelSize = 22 / view.scale
            return <g key={region.id} className={`evidence-region ${region.text ? 'text-highlight' : ''} ${index === active ? 'is-active' : ''}`} data-testid={`evidence-box-${region.label}`} aria-label={`${region.text ? 'Text source' : 'Box'} ${region.label}`}>
              <title>{region.text ? citation.quote ?? 'Text source' : region.id}</title>
              <rect x={x} y={y} width={Math.max(0, right - x)} height={Math.max(0, bottom - y)} vectorEffect="non-scaling-stroke" />
              <svg x={x} y={y} width={labelSize} height={labelSize} viewBox="0 0 22 22" overflow="visible"><rect className="evidence-label-bg" width="22" height="22" rx="5" /><text x="11" y="15" textAnchor="middle">{region.label}</text></svg>
            </g>
          })}
        </svg>}
      </div>}
      {error ? <div className="viewer-message"><p role="alert">{error}</p><Button variant="raised" onClick={() => setRetry(retry + 1)}>Try again</Button></div>
        : !image && <p className="viewer-message" role="status">Loading drawing…</p>}
    </div>
    <span className="viewer-3d-slot">{(answer.evidence.scene.doc_id || answer.doc_ids[0]) === citation.doc_id
      ? <VisualiseItButton answer={answer} /> : <VisualiseItButton docId={citation.doc_id} />}</span>
    <footer className="drawing-credit" data-testid="drawing-credit">{doc ? <>{doc.credit || 'Credit not supplied'} · {doc.licence || 'Licence not supplied'}</> : 'Loading source credit…'}</footer>
  </aside>
}
