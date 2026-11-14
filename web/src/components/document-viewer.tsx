import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { ChevronDown, ChevronLeft, ChevronRight, Download, FileSymlink, FileText, Highlighter, Maximize2, Minus, PenLine, Plus, Search, X } from 'lucide-react'
import { workspaceApi } from '../lib/api'
import type { Answer, Citation, Document } from '../lib/types'
import { fitPage, focusBox, zoomAt, type PageTransform, type Point, type Size } from '../lib/page-transform'
import { viewerEvidence } from '../lib/viewer-evidence'
import { Button } from './ui'
import { setHover, setSelected, useLinkedItem } from '../viewer3d'
import './document-viewer.css'
import { answerTableSelection } from '../lib/ar-bridge'
import { ShowOnTableButton } from './show-on-table'
import { itemIsHidden, type DrawingEdits } from '../lib/scene-edits'
import type { SceneCommand } from '../viewer3d/commands'
import { DrawingModel, ViewerModeToggle, type ViewerMode } from './drawing-model'
import { ItemPanel } from './item-panel'
import { placeEvidence, type ItemPlace, type LinkedItem } from '../lib/linked'

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

export function DocumentViewer({ answer, citation: originalCitation, sheet, onClose, edits, commands, chatId }: {
  answer: Answer; citation: Citation; sheet: boolean; onClose: () => void
  edits?: DrawingEdits; commands?: readonly SceneCommand[]
  chatId?: string | null
}) {
  const [mode, setMode] = useState<ViewerMode>('2d')
  const [modelVisited, setModelVisited] = useState(false)
  function changeMode(next: ViewerMode) { setMode(next); if (next === '3d') setModelVisited(true) }
  const [place, setPlace] = useState<{ location: ItemPlace; item: LinkedItem } | null>(null)
  const [selectedItem, setSelectedItem] = useState<{ docId: string; itemId: string } | null>(null)
  const itemTrigger = useRef<Element | null>(null)
  const citation = place ? { ...originalCitation, doc_id: place.location.doc_id, page: place.location.page, item_ids: [place.item.item_id] } : originalCitation
  const { regions, sources, initial } = useMemo(() => place ? placeEvidence(place.location, place.item) : viewerEvidence(answer, originalCitation), [answer, originalCitation, place])
  const table = answerTableSelection(answer)
  const [active, setActive] = useState(initial)
  const [doc, setDoc] = useState<Document | null>(null)
  const [imageUrl, setImageUrl] = useState('')
  const [image, setImage] = useState<Size | null>(null)
  const [viewport, setViewport] = useState<Size>({ width: 0, height: 0 })
  const [view, setView] = useState<PageTransform>({ x: 0, y: 0, scale: 1 })
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const [documentTags, setDocumentTags] = useState<Record<string, string>>({})
  const tags = { ...documentTags, ...edits?.tags }
  const visualiseAnswer = useMemo(() => commands ? {
    ...answer, evidence: { ...answer.evidence, scene: { ...answer.evidence.scene, commands } },
  } : answer, [answer, commands])
  const linked = useLinkedItem()
  const stage = useRef<HTMLDivElement>(null)
  const panel = useRef<HTMLElement>(null)
  const close = useRef<HTMLButtonElement>(null)
  const pointers = useRef(new Map<number, Point>())
  const returnFocus = useRef(typeof document !== 'undefined' ? document.activeElement as HTMLElement | null : null)

  useEffect(() => { setPlace(null); setSelectedItem(null) }, [originalCitation])
  function closeItem() {
    setSelectedItem(null)
    requestAnimationFrame(() => {
      const trigger = itemTrigger.current
      if (trigger?.isConnected) (trigger as SVGElement | HTMLElement).focus()
      else stage.current?.focus()
    })
  }
  function openItem(index: number, id: string, trigger: Element) {
    setActive(index); setSelected(id, '2d')
    itemTrigger.current = trigger
    setSelectedItem({ docId: citation.doc_id, itemId: sources[index]?.itemIds[0] ?? id })
  }

  useEffect(() => {
    const controller = new AbortController()
    setDocumentTags({})
    workspaceApi.getDocumentTags(citation.doc_id, controller.signal).then((value) => {
      if (!controller.signal.aborted) setDocumentTags(value)
    }).catch(() => {})
    return () => controller.abort()
  }, [citation.doc_id])

  useEffect(() => {
    if (linked.selectedSource !== '3d') return
    const index = sources.findIndex((source) => source.itemIds.includes(linked.selected ?? ''))
    if (index >= 0) setActive(index)
  }, [linked.selected, linked.selectedSource, sources])
  useEffect(() => {
    setHover(null, '2d'); setSelected(null, '2d')
    return () => { setHover(null, '2d'); setSelected(null, '2d') }
  }, [citation.doc_id, citation.page])

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
    const bbox = sources[active]?.bbox
    setView(bbox ? focusBox(bbox, viewport, fitted.scale) : fitted)
  }, [image, viewport, active, sources])

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
  function selectSource(index: number) {
    setActive(index)
    setSelected(sources[index]?.itemIds[0] ?? null, '2d')
  }

  return <aside ref={panel} className={`document-viewer ${sheet ? 'viewer-sheet' : ''}`} role={sheet ? 'dialog' : 'region'} aria-modal={sheet || undefined} aria-label="Drawing viewer"
    onKeyDown={(event) => {
      if (mode === '3d' && event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); changeMode('2d'); return }
      if (event.key === 'Escape') { event.stopPropagation(); if (selectedItem) closeItem(); else onClose() }
      if (sheet && event.key === 'Tab') {
        const controls = Array.from(panel.current?.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], [tabindex="0"]') ?? []).filter((node) => node.getClientRects().length)
        if (!controls?.length) return
        const first = controls[0], last = controls[controls.length - 1]
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
        if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
      }
    }}>
    <header className="viewer-heading"><FileText size={24} /><div><strong>{doc?.title ?? citation.doc_id}</strong><small>/{doc?.source || 'Drawings'}</small></div>
      <ViewerModeToggle mode={mode} onChange={changeMode} />
      <div className="viewer-source-nav" hidden={mode === '3d'}>
        <a className="viewer-open-source" aria-label="Open source page" href={imageUrl || undefined} target="_blank" rel="noreferrer"><FileSymlink size={16} /></a>
        <Button variant="ghost" size="icon" aria-label="Previous source" disabled={active <= 0} onClick={() => selectSource(active - 1)}><ChevronLeft size={16} /></Button>
        <span aria-live="polite" data-testid="source-position">{sources.length ? active + 1 : 0} of {sources.length}</span>
        <ChevronDown className="viewer-source-chevron" size={14} aria-hidden="true" />
        <Button variant="ghost" size="icon" aria-label="Next source" disabled={active >= sources.length - 1} onClick={() => selectSource(active + 1)}><ChevronRight size={16} /></Button>
        <Button className="viewer-fit" variant="ghost" size="icon" aria-label="Fit drawing" disabled={!image} onClick={() => image && setView(fitPage(image, viewport))}><Maximize2 size={16} /></Button>
      </div>
      <ShowOnTableButton docId={citation.doc_id} itemIds={table?.doc_id === citation.doc_id ? table.item_ids : citation.item_ids} chatId={chatId} />
      <button ref={close} type="button" className="button button-ghost button-size-icon" aria-label="Close drawing viewer" onClick={onClose}><X size={18} /></button>
    </header>
    <div className="viewer-toolbar" aria-label="Drawing controls" hidden={mode === '3d'}>
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
    <div className="viewer-item-layout" hidden={mode === '3d'}>
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
            const label = region.label
            const tag = tags[region.id]
            const secondaryTag = answer.evidence.scene.commands?.length && tag !== label ? tag : undefined
            const hidden = itemIsHidden(edits, region.id)
            return <g key={region.id} className={`evidence-region ${region.text ? 'text-highlight' : ''} ${index === active || linked.selected === region.id || linked.hovered === region.id ? 'is-active' : ''} ${hidden ? 'is-hidden' : ''}`} data-testid={`evidence-box-${region.label}`} aria-label={`${region.text ? 'Text source' : 'Box'} ${label}${secondaryTag ? `, ${secondaryTag}` : ''}${hidden ? ', hidden' : ''}`}
              data-item-id={region.id} data-linked={linked.selected === region.id || linked.hovered === region.id ? 'true' : undefined}
              data-hidden={String(hidden)} data-tag={tag}
              role="button" tabIndex={0} aria-haspopup={sheet ? 'dialog' : undefined}
              onPointerDown={(event) => event.stopPropagation()}
              onMouseEnter={() => setHover(region.id, '2d')} onMouseLeave={() => setHover(null, '2d')}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); openItem(index, region.id, event.currentTarget) }
              }}
              onClick={(event) => openItem(index, region.id, event.currentTarget)}>
              <title>{region.text ? citation.quote ?? 'Text source' : region.id}</title>
              <rect x={x} y={y} width={Math.max(0, right - x)} height={Math.max(0, bottom - y)} vectorEffect="non-scaling-stroke" />
              <svg x={x} y={y} width={labelSize * Math.max(1, label.length / 2)} height={labelSize} viewBox={`0 0 ${22 * Math.max(1, label.length / 2)} 22`} overflow="visible"><rect className="evidence-label-bg" width={22 * Math.max(1, label.length / 2)} height="22" rx="5" /><text x={11 * Math.max(1, label.length / 2)} y="15" textAnchor="middle">{label}</text></svg>
              {secondaryTag && <svg className="evidence-secondary-tag" x={x + labelSize * Math.max(1, label.length / 2)} y={y} width={labelSize * Math.max(1, secondaryTag.length / 2)} height={labelSize} viewBox={`0 0 ${22 * Math.max(1, secondaryTag.length / 2)} 22`}><text x="4" y="15">{secondaryTag}</text></svg>}
            </g>
          })}
        </svg>}
      </div>}
      {error ? <div className="viewer-message"><p role="alert">{error}</p><Button variant="raised" onClick={() => setRetry(retry + 1)}>Try again</Button></div>
        : !image && <p className="viewer-message" role="status">Loading drawing…</p>}
    </div>
    {selectedItem && <ItemPanel docId={selectedItem.docId} itemId={selectedItem.itemId} sheet={sheet} onClose={closeItem} onOpenPlace={(location, item) => {
      setPlace({ location, item }); setActive(0); setSelected(item.item_id, '2d')
      if (sheet) closeItem()
    }} />}
    </div>
    {modelVisited && <div className="viewer-model-slot" hidden={mode !== '3d'}>
      <DrawingModel docId={citation.doc_id} chatId={chatId} answer={(answer.evidence.scene.doc_id || answer.doc_ids[0]) === citation.doc_id ? visualiseAnswer : undefined} />
    </div>}
    <div className="viewer-3d-slot" hidden={mode === '3d'}><button type="button" className="viewer3d-visualise-button" onClick={() => changeMode('3d')}>Visualise it</button></div>
    <footer className="drawing-credit" data-testid="drawing-credit">{doc ? <>{doc.credit || 'Credit not supplied'} · {doc.licence || 'Licence not supplied'}</> : 'Loading source credit…'}</footer>
  </aside>
}
