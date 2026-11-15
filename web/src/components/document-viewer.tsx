import type { Alignment, OverlayDoc } from '../lib/sheet-overlay'
import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { ChevronLeft, ChevronRight, Download, FileSymlink, FileText, Highlighter, Layers, Maximize2, Minus, PenLine, Plus, Ruler, Search, X } from 'lucide-react'
import { ReadOnceChip } from './read-once-chip'
import { SheetOverlay } from './sheet-overlay'
import { workspaceApi } from '../lib/api'
import type { Answer, Citation, Document } from '../lib/types'
import { fitPage, focusBox, focusBoxWithin, zoomAt, type PageTransform, type Point, type Size } from '../lib/page-transform'
import { viewerEvidence } from '../lib/viewer-evidence'
import { pickItemAt, pickPlanItem, type PickBox, type PlanPickItem } from '../lib/pick-item'
import { Button } from './ui'
import { setHover, setSelected, useLinkedItem } from '../viewer3d'
import './document-viewer.css'
import { answerTableSelection } from '../lib/ar-bridge'
import { ShowOnTableButton } from './show-on-table'
import { itemIsHidden, type DrawingEdits } from '../lib/scene-edits'
import type { SceneCommand } from '../viewer3d/commands'
import { DrawingModel, ViewerModeToggle, type ViewerMode } from './drawing-model'
import { ItemPanel } from './item-panel'
import { KindLegend } from '../viewer3d/KindLegend'
import { kindFromItemId, kindStyle } from '../lib/kind-colors'
import { placeEvidence, type ItemPlace, type LinkedItem } from '../lib/linked'
import { AnnotationLayer, useAnnotations, type Annotation, type MarkupTool } from './viewer-tools/annotations'
import { findSheetText, loadSheetText, type SheetText } from './viewer-tools/sheet-text'
import { RoomLabels } from './viewer-tools/room-labels'
import { ViewRegions } from './viewer-tools/view-regions'
import { SpecPanel } from './viewer-tools/spec-panel'
import { CalculationPanel } from './calc-panel'
import { ErrorBoundary } from './error-boundary'
import type { FocusTarget } from '../lib/calc-view'
import { downloadSource } from './viewer-tools/download-source'
import { TellStoaBubble } from './viewer-tools/tell-stoa-bubble'
import './viewer-tools/tell-stoa-bubble.css'
import { markBox, SymbolMarkupLayer, SymbolMarkupPanel, SymbolMarkupTools, useSymbolMarkup } from './viewer-tools/symbol-markup'
import { useDrawingHighlights } from '../viewer3d/useDrawingHighlights'
import { PlanHoverTip } from './viewer-tools/plan-hover-tip'
import { planItemSummary } from '../lib/plan-item-summary'
import { PlanLayerChips, PlanLayerShapes, usePlanLayers } from './viewer-tools/plan-layers'
import { MeasureLayer, useMeasure } from './viewer-tools/measure-layer'
import './viewer-tools/measure-layer.css'
import './viewer-tools/plan-layers.css'
import { snapPoint, formatM, formatM2, type Pt } from '../lib/measure'

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

export function DocumentViewer({ answer, citation: originalCitation, sheet, onClose, edits, commands, chatId, initialMode, initialPanel, openRequest, initialOverlayDocId, onOverlayAlignment }: {
  onOverlayAlignment?: (result: Alignment, base: OverlayDoc, overlay: OverlayDoc, basePage: number, overlayPage: number) => void
  initialOverlayDocId?: string | null
  /** Changes on every open request, so "Visualise it" re-opens 3D after the user toggled back to 2D. */
  openRequest?: number
  /** Opens straight in this view (the answer card's "Visualise it" passes '3d'). */
  initialMode?: ViewerMode
  /** Opens with the Calculation panel in the side slot (the evidence card's "Show calculation"). */
  initialPanel?: 'calc'
  answer: Answer; citation: Citation; sheet: boolean; onClose: () => void
  edits?: DrawingEdits; commands?: readonly SceneCommand[]
  chatId?: string | null
}) {
  const [overlayOpen, setOverlayOpen] = useState(initialOverlayDocId !== undefined)
  useEffect(() => { if (initialOverlayDocId !== undefined) setOverlayOpen(true) }, [initialOverlayDocId, openRequest])
  const [mode, setMode] = useState<ViewerMode>(initialMode ?? '2d')
  const [modelVisited, setModelVisited] = useState(initialMode === '3d')
  function changeMode(next: ViewerMode) { setMode(next); if (next === '3d') setModelVisited(true) }
  // Each new open (another citation or Visualise it click) starts in the requested view.
  useEffect(() => { if (initialMode) changeMode(initialMode) }, [initialMode, originalCitation, openRequest]) // eslint-disable-line react-hooks/exhaustive-deps
  const [place, setPlace] = useState<{ location: ItemPlace; item: LinkedItem } | null>(null)
  const [selectedItem, setSelectedItem] = useState<{ docId: string; itemId: string } | null>(null)
  const [pageNumber, setPageNumber] = useState(originalCitation.page)
  const [calcSource, setCalcSource] = useState<Citation | null>(null)
  const itemTrigger = useRef<Element | null>(null)
  const citation = useMemo(() => place ? { ...originalCitation, kind: 'element' as const, quote: null, doc_id: place.location.doc_id, page: place.location.page, item_ids: [place.item.item_id] } : { ...(calcSource ?? originalCitation), page: pageNumber }, [originalCitation, calcSource, place, pageNumber])
  const { regions, sources, initial } = useMemo(() => place ? placeEvidence(place.location, place.item) : viewerEvidence(calcSource ? { ...answer, citations: [...answer.citations.filter((entry) => entry.n !== calcSource.n || entry.doc_id !== calcSource.doc_id || entry.page !== calcSource.page), calcSource] } : answer, citation), [answer, citation, place, calcSource])
  // Every plan-map item on this page: picks one item inside an aggregate highlight, and lets a click anywhere
  // on the plan open that item's details (plain code over the plan map, no model call, no 3D needed).
  const [planItems, setPlanItems] = useState<(PlanPickItem & { label?: string | null; props?: Record<string, unknown> | null })[]>([])
  const [mPerPx, setMPerPx] = useState<number | null>(null)
  const layers = usePlanLayers()
  const measure = useMeasure(mPerPx)
  const stopMeasure = measure.stop
  useEffect(() => {
    const controller = new AbortController()
    setPlanItems([]); setMPerPx(null); stopMeasure()
    workspaceApi.getPlanMap(citation.doc_id, citation.page, controller.signal).then((pm) => {
      if (controller.signal.aborted) return
      setMPerPx(typeof pm.scale?.m_per_px === 'number' && pm.scale.m_per_px > 0 ? pm.scale.m_per_px : null)
      setPlanItems((pm.items ?? []).flatMap((item) => item.bbox_px ? [{ id: item.item_id, kind: item.kind ?? kindFromItemId(item.item_id) ?? 'other', bbox: item.bbox_px, polygon: item.polygon_px ?? null, role: typeof item.props?.role === 'string' ? item.props.role : null, label: item.label ?? null, props: item.props ?? null }] : []))
    }).catch(() => {})
    return () => controller.abort()
  }, [citation.doc_id, citation.page, stopMeasure])
  const pickBoxes = useMemo<PickBox[]>(() => planItems.map(({ id, bbox }) => ({ id, bbox })), [planItems])
  const planById = useMemo(() => new Map(planItems.map((item) => [item.id, item])), [planItems])
  const [hoverPick, setHoverPick] = useState<string | null>(null)
  const [hoverAt, setHoverAt] = useState<Point | null>(null)
  const tapStart = useRef<{ id: number; x: number; y: number } | null>(null)
  // A plain tap inspects after a short wait, so the two taps of a double-click (zoom) do not open the item panel.
  const inspectTimer = useRef<number | null>(null)
  function cancelInspect() { if (inspectTimer.current !== null) { window.clearTimeout(inspectTimer.current); inspectTimer.current = null } }
  useEffect(() => cancelInspect, [])
  const highlights = useDrawingHighlights(citation.doc_id, answer.answer_id, chatId)
  const answerSelection = !place && answer.citations.some((entry) => entry.doc_id === citation.doc_id && entry.page === citation.page && (entry.item_ids.length > 0 || entry.kind === 'text' || !!entry.bbox_px))
  const navigationKind = answerSelection ? 'highlight' : 'item'
  const table = answerTableSelection(answer)
  const [active, setActive] = useState(initial)
  const [doc, setDoc] = useState<Document | null>(null)
  const [imageUrl, setImageUrl] = useState('')
  const [image, setImage] = useState<Size | null>(null)
  const [viewport, setViewport] = useState<Size>({ width: 0, height: 0 })
  const [view, setView] = useState<PageTransform>({ x: 0, y: 0, scale: 1 })
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const [tool, setTool] = useState<MarkupTool>('pan')
  const [draft, setDraft] = useState<Annotation | null>(null)
  const drawingPointer = useRef<number | null>(null)
  const draftRef = useRef<Annotation | null>(null)
  const annotations = useAnnotations(citation.doc_id, citation.page)
  const markup = useSymbolMarkup(citation.doc_id, citation.page)
  const [searchOpen, setSearchOpen] = useState(false)
  const [showViews, setShowViews] = useState(false)
  const [layersOpen, setLayersOpen] = useState(false)
  const searchTrigger = useRef<HTMLButtonElement>(null)
  const titleId = useId()
  function closeSearch() { setSearchOpen(false); searchTrigger.current?.focus() }
  const [query, setQuery] = useState('')
  const [sheetText, setSheetText] = useState<SheetText[]>([])
  const [textStatus, setTextStatus] = useState('')
  const [hitIndex, setHitIndex] = useState(0)
  const hits = useMemo(() => searchOpen ? findSheetText(sheetText, query) : [], [sheetText, query, searchOpen])
  const [calcOpen, setCalcOpen] = useState(initialPanel === 'calc' && !!answer.reasoning)
  useEffect(() => { setCalcOpen(initialPanel === 'calc' && !!answer.reasoning) }, [initialPanel, openRequest]) // eslint-disable-line react-hooks/exhaustive-deps
  const [specOpen, setSpecOpen] = useState(originalCitation.kind === 'text' || !!originalCitation.quote)
  function sourcePassage(index: number) {
    const source = sources[index]
    return source && answer.citations.find((entry) => entry.doc_id === citation.doc_id && entry.page === citation.page && (entry.kind === 'text' || entry.quote) &&
      (`citation-${entry.n}` === source.id || entry.item_ids.some((id) => source.itemIds.includes(id)) || (entry.bbox_px && source.bbox && entry.bbox_px.every((value, axis) => value === source.bbox![axis]))))
  }
  const activeTextCitation = sourcePassage(active)
    ?? (citation.doc_id === originalCitation.doc_id && citation.page === originalCitation.page ? citation : null)
  const specCitation = activeTextCitation && (activeTextCitation.kind === 'text' || activeTextCitation.quote) ? activeTextCitation : null
  const [downloading, setDownloading] = useState(false)
  const [downloadError, setDownloadError] = useState('')
  const [documentTags, setDocumentTags] = useState<Record<string, string>>({})
  const tags = { ...documentTags, ...edits?.tags }
  const visualiseAnswer = useMemo(() => commands ? {
    ...answer, evidence: { ...answer.evidence, scene: { ...answer.evidence.scene, commands } },
  } : answer, [answer, commands])
  const linked = useLinkedItem()
  const stage = useRef<HTMLDivElement>(null)
  // Kinds of every item the answer names (all pages): the legend leads with these totals.
  const totalKinds = useMemo(() => {
    const kinds = new Map<string, string>()
    for (const id of answer.evidence.scene.highlight_item_ids) { const kind = kindFromItemId(id); if (kind) kinds.set(id, kind) }
    for (const source of answer.citations) for (const id of source.item_ids) { const kind = source.item_kind ?? kindFromItemId(id); if (kind) kinds.set(id, kind) }
    return [...kinds.values()]
  }, [answer])
  // Number tags are 22 px on screen. Keep the first tag in any overlapping group; the rest show on hover or zoom.
  const shownTags = useMemo(() => {
    const shown = new Set<string>()
    const placed: { x: number; y: number; w: number }[] = []
    const order = regions.map((region, index) => ({ region, index }))
      .sort((a, b) => Number(b.index === active) - Number(a.index === active))
    for (const { region } of order) {
      const x = region.bbox[0] * view.scale, y = region.bbox[1] * view.scale, w = 22 * Math.max(1, region.label.length / 2)
      if (placed.some((tag) => x < tag.x + tag.w + 2 && x + w + 2 > tag.x && Math.abs(y - tag.y) < 24)) continue
      placed.push({ x, y, w }); shown.add(region.id)
    }
    return shown
  }, [regions, view.scale, active])
  const panel = useRef<HTMLElement>(null)
  const close = useRef<HTMLButtonElement>(null)
  const pointers = useRef(new Map<number, Point>())
  const returnFocus = useRef(typeof document !== 'undefined' ? document.activeElement as HTMLElement | null : null)

  useEffect(() => {
    setPlace(null); setCalcSource(null); setSelectedItem(null); setPageNumber(originalCitation.page)
    setSpecOpen(originalCitation.kind === 'text' || !!originalCitation.quote)
  }, [originalCitation])
  useEffect(() => { setActive(initial) }, [initial, sources, citation.doc_id, citation.page])
  useEffect(() => {
    setDraft(null); draftRef.current = null; drawingPointer.current = null; pointers.current.clear()
    setQuery(''); setHitIndex(0); setSheetText([]); setDownloadError(''); setTool('pan')
  }, [citation.doc_id, citation.page])
  useEffect(() => {
    if (!searchOpen && !(specOpen && specCitation)) return
    const controller = new AbortController()
    setTextStatus('Loading sheet text…')
    loadSheetText(citation.doc_id, citation.page, controller.signal).then((text) => {
      if (controller.signal.aborted) return
      setSheetText(text); setTextStatus(text.length ? '' : 'No searchable text is available on this sheet.')
    }).catch((err: unknown) => { if (!controller.signal.aborted) setTextStatus(err instanceof Error ? err.message : 'Sheet text could not be loaded.') })
    return () => controller.abort()
  }, [citation.doc_id, citation.page, searchOpen, specOpen, !!specCitation])
  useEffect(() => {
    const bbox = hits[hitIndex]?.bbox
    if (image && bbox && viewport.width && viewport.height) setView(focusBoxWithin(bbox, viewport, image, fitPage(image, viewport)))
  }, [hits, hitIndex, image, viewport])
  function closeItem() {
    setSelectedItem(null)
    requestAnimationFrame(() => {
      const trigger = itemTrigger.current
      if (trigger?.isConnected) (trigger as SVGElement | HTMLElement).focus()
      else stage.current?.focus()
    })
  }
  /** A calculation source was clicked: highlight its box on the drawing (the same highlight a citation gives). */
  function focusCalcItem(target: FocusTarget) {
    const sourceDoc = target.doc_id ?? citation.doc_id
    const sourcePage = target.page ?? pageNumber
    const cited = answer.citations.find((entry) => entry.doc_id === sourceDoc && entry.page === sourcePage && (target.cite != null ? entry.n === target.cite : entry.item_ids.includes(target.item_id)))
    const box = answer.evidence.boxes.find((entry) => entry.item_id === target.item_id && entry.page === sourcePage && (!entry.doc_id || entry.doc_id === sourceDoc))
    setPlace(null)
    setCalcSource({ n: target.cite ?? cited?.n ?? 0, doc_id: sourceDoc, page: sourcePage, kind: 'region', bbox_px: target.bbox ?? cited?.bbox_px ?? box?.bbox_px ?? null, item_ids: [target.item_id], quote: null })
    if (target.page != null && target.page !== pageNumber) setPageNumber(target.page)
    const index = sources.findIndex((source) => source.itemIds.includes(target.item_id))
    if (index >= 0) setActive(index)
    setSelected(target.item_id, '2d')
    if (window.matchMedia?.('(max-width: 800px)').matches) setCalcOpen(false)
  }
  /** An aggregate highlight covers several items: choose the one under the click, else keep the aggregate's first. */
  function itemUnder(index: number, event?: { clientX: number; clientY: number; currentTarget: Element }): string | null {
    const ids = sources[index]?.itemIds ?? []
    const svg = (event?.currentTarget as SVGGraphicsElement | undefined)?.ownerSVGElement
    if (!event || !svg || !image || ids.length < 2) return null
    const rect = svg.getBoundingClientRect()
    if (!rect.width || !rect.height) return null
    const point: [number, number] = [(event.clientX - rect.left) / rect.width * image.width, (event.clientY - rect.top) / rect.height * image.height]
    return pickItemAt(point, pickBoxes, ids, 6 / Math.max(view.scale, .001))
  }
  function openItem(index: number, id: string, trigger: Element, event?: { clientX: number; clientY: number; currentTarget: Element }) {
    const picked = itemUnder(index, event)
    setActive(index); setSelected(picked ?? id, '2d')
    if (sourcePassage(index)) { setSpecOpen(true); setSelectedItem(null); return }
    setSpecOpen(false)
    itemTrigger.current = trigger
    setSelectedItem({ docId: citation.doc_id, itemId: picked ?? sources[index]?.itemIds[0] ?? id })
  }
  /** Page-pixel point under the pointer, or null when it is off the page. */
  function rawPagePoint(clientX: number, clientY: number): [number, number] | null {
    if (!image || !stage.current) return null
    const point = pointerPoint(clientX, clientY)
    const x = (point.x - view.x) / view.scale, y = (point.y - view.y) / view.scale
    return x < 0 || y < 0 || x > image.width || y > image.height ? null : [x, y]
  }
  function planItemAt(clientX: number, clientY: number): string | null {
    if (!planItems.length || tool !== 'pan' || markup.mode || measure.mode || shownPage !== citation.page) return null
    const point = rawPagePoint(clientX, clientY)
    return point ? pickPlanItem(point, planItems, Math.min(6 / Math.max(view.scale, .001), 24)) : null
  }
  /** A click on the plan outside any answer box: show the details of the item under it. */
  function inspectAt(clientX: number, clientY: number) {
    if (measure.mode) {
      const point = rawPagePoint(clientX, clientY)
      if (point) measure.add(snapPoint(point as Pt, planItems, 8 / Math.max(view.scale, .001)))
      return
    }
    const id = planItemAt(clientX, clientY)
    if (!id) return
    setSpecOpen(false)
    itemTrigger.current = stage.current
    setSelected(id, '2d')
    setSelectedItem({ docId: citation.doc_id, itemId: id })
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

  // The page being shown. A new page of the same document loads behind the old one and swaps in place (same <img> node,
  // no blank frame); evidence for the new page waits until its image has painted.
  const urlRef = useRef('')
  const loadingPage = useRef(citation.page)
  const loadedDoc = useRef('')
  const [shownPage, setShownPage] = useState(citation.page)
  useEffect(() => () => { if (urlRef.current) URL.revokeObjectURL(urlRef.current) }, [])
  useEffect(() => {
    const controller = new AbortController()
    let disposed = false
    setError('')
    if (loadedDoc.current !== citation.doc_id || retry) {
      setDoc(null)
      setImageUrl('')
      setImage(null)
    }
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
        const url = URL.createObjectURL(blob)
        const old = urlRef.current
        urlRef.current = url
        loadedDoc.current = citation.doc_id
        loadingPage.current = citation.page
        setDoc(metadata)
        setImageUrl(url)
        if (old) setTimeout(() => URL.revokeObjectURL(old), 1000)
      }).catch((err: unknown) => {
        if (!disposed) setError(err instanceof Error ? err.message : 'The drawing could not be loaded.')
      })
    return () => { disposed = true; controller.abort() }
  }, [citation.doc_id, citation.page, retry])

  useLayoutEffect(() => {
    const node = stage.current
    if (!node) return
    const observer = new ResizeObserver(() => setViewport({ width: node.clientWidth, height: node.clientHeight }))
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  // A new answer about the open sheet swaps the boxes in place: keep zoom/pan, fade old boxes out and new ones in.
  const answerId = useRef(answer.answer_id)
  const keepView = useRef(false)
  const previousRegions = useRef({ key: `${citation.doc_id}:${citation.page}`, regions })
  const [leaving, setLeaving] = useState<typeof regions>([])
  useEffect(() => {
    if (answerId.current !== answer.answer_id) { answerId.current = answer.answer_id; keepView.current = true }
  }, [answer.answer_id])
  useEffect(() => {
    const key = `${citation.doc_id}:${citation.page}`
    const before = previousRegions.current
    previousRegions.current = { key, regions }
    if (before.regions === regions) return
    if (before.key !== key) { setLeaving([]); return }
    const next = new Set(regions.map((region) => region.id))
    const gone = before.regions.filter((region) => !next.has(region.id))
    setLeaving(gone)
    if (!gone.length) return
    const timer = window.setTimeout(() => setLeaving([]), 450)
    return () => window.clearTimeout(timer)
  }, [regions, citation.doc_id, citation.page])

  useEffect(() => {
    if (!image || !viewport.width || !viewport.height) return
    if (keepView.current) { keepView.current = false; return }
    const fitted = fitPage(image, viewport)
    const bbox = sources[active]?.bbox
    setView(bbox ? focusBoxWithin(bbox, viewport, image, fitted) : fitted)
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
  function pagePoint(clientX: number, clientY: number): Point {
    const point = pointerPoint(clientX, clientY)
    return { x: Math.max(0, Math.min(image?.width ?? 0, (point.x - view.x) / view.scale)), y: Math.max(0, Math.min(image?.height ?? 0, (point.y - view.y) / view.scale)) }
  }
  function finishAnnotation(pointerId: number, save: boolean) {
    if (drawingPointer.current !== pointerId) return
    if (save && draftRef.current?.tool === 'marker') {
      // Dragging with the highlighter marks an item: the Tell Stoa bubble opens for the dragged box.
      const [a, b] = draftRef.current.points
      const box: [number, number, number, number] = [Math.min(a.x, b.x), Math.min(a.y, b.y), Math.max(a.x, b.x), Math.max(a.y, b.y)]
      if (box[2] - box[0] >= 4 && box[3] - box[1] >= 4) markup.select({ box })
    } else if (save && draftRef.current) annotations.add(draftRef.current)
    drawingPointer.current = null; draftRef.current = null; setDraft(null)
  }
  function chooseTool(next: MarkupTool) {
    drawingPointer.current = null; draftRef.current = null; setDraft(null); pointers.current.clear()
    setTool((previous) => previous === next ? 'pan' : next)
  }
  function changePage(next: number) { setPlace(null); setSelectedItem(null); setPageNumber(next); setActive(0) }
  async function download() {
    setDownloading(true); setDownloadError('')
    try { await downloadSource(citation.doc_id) }
    catch (err) { setDownloadError(err instanceof Error ? err.message : 'The source could not be downloaded.') }
    finally { setDownloading(false) }
  }
  function selectSource(index: number) {
    setActive(index)
    if (sourcePassage(index)) { setSpecOpen(true); setSelectedItem(null) }
    setSelected(sources[index]?.itemIds[0] ?? null, '2d')
  }

  // IFC docs report pages=1 though each storey has a plan page; never show "2 / 1".
  const totalPages = doc ? Math.max(doc.pages, citation.page) : undefined
  return <aside ref={panel} className={`document-viewer ${sheet ? 'viewer-sheet' : ''}`} role={sheet ? 'dialog' : 'region'} aria-modal={sheet || undefined} aria-label={sheet ? undefined : "Drawing viewer"} aria-labelledby={sheet ? titleId : undefined}
    onKeyDown={(event) => {
      if (mode === '3d' && event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); changeMode('2d'); return }
      const typing = event.target instanceof HTMLElement && ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(event.target.tagName)
      if (mode === '2d' && measure.mode && !typing && (event.key === 'Enter' || event.key === 'Backspace')) { event.preventDefault(); if (event.key === 'Enter') measure.close(); else measure.undo(); return }
      if (mode === '2d' && event.key === 'Escape' && measure.mode) { event.stopPropagation(); measure.stop(); return }
      if (event.key === 'Escape') { event.stopPropagation(); if (markup.selection || markup.mode || markup.editing) markup.cancel(); else if (markup.open) markup.close(); else if (searchOpen) closeSearch(); else if (tool !== 'pan') chooseTool('pan'); else if (selectedItem) closeItem(); else onClose() }
      if (sheet && event.key === 'Tab') {
        const controls = Array.from(panel.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), a[href], [tabindex="0"]') ?? []).filter((node) => node.getClientRects().length)
        if (!controls?.length) return
        const first = controls[0], last = controls[controls.length - 1]
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
        if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
      }
    }}>
    <header className="viewer-heading"><FileText size={24} /><div><strong id={titleId}>{doc?.title ?? citation.doc_id}</strong><small>/{doc?.source || 'Drawings'}<ReadOnceChip docId={citation.doc_id} /></small></div>
      <Button variant="ghost" size="xs" className="overlay-open-button" onClick={() => setOverlayOpen(true)}>Overlay with…</Button>
      <ViewerModeToggle mode={mode} onChange={changeMode} />
      <div className="viewer-source-nav" hidden={mode === '3d'}>
        {imageUrl && <a className="viewer-open-source" aria-label="Open source page" href={imageUrl} target="_blank" rel="noreferrer"><FileSymlink size={16} /></a>}
        {!highlights.cleared && sources.length > 0 && <>
          <Button variant="ghost" size="icon" aria-label={`Previous ${navigationKind}`} title={`Previous ${navigationKind}`} disabled={active <= 0} onClick={() => selectSource(active - 1)}><ChevronLeft size={16} /></Button>
          <span aria-live="polite" data-testid="source-position">{answerSelection ? 'Highlight' : 'Item'} {Math.min(active + 1, sources.length)} of {sources.length}{answerSelection ? '' : ' on this drawing'}</span>
          <Button variant="ghost" size="icon" aria-label={`Next ${navigationKind}`} title={`Next ${navigationKind}`} disabled={active >= sources.length - 1} onClick={() => selectSource(active + 1)}><ChevronRight size={16} /></Button>
        </>}
        <Button className="viewer-fit" variant="ghost" size="icon" aria-label="Fit drawing" disabled={!image} onClick={() => image && setView(fitPage(image, viewport))}><Maximize2 size={16} /></Button>
      </div>
      <ShowOnTableButton docId={citation.doc_id} itemIds={table?.doc_id === citation.doc_id ? table.item_ids : citation.item_ids} chatId={chatId} />
      <button ref={close} type="button" className="button button-ghost button-size-icon" aria-label="Close drawing viewer" onClick={onClose}><X size={18} /></button>
    </header>
    <div className="viewer-toolbar" aria-label="Drawing controls" hidden={mode === '3d'}>
      <div className="viewer-page-position"><Button variant="ghost" size="icon-xs" aria-label="Previous page" disabled={citation.page <= 1} onClick={() => changePage(citation.page - 1)}><ChevronLeft size={14} /></Button><span className="page-number">{citation.page}</span><span>/ {totalPages ?? '…'}</span><Button variant="ghost" size="icon-xs" aria-label="Next page" disabled={!totalPages || citation.page >= totalPages} onClick={() => changePage(citation.page + 1)}><ChevronRight size={14} /></Button></div>
      <span className="toolbar-spacer" />
      <Button variant="ghost" size="xs" onClick={highlights.clear}>Clear highlights</Button>
      {mode === '2d' && planItems.length > 0 && <div className="viewer-layers-menu" onKeyDown={(event) => { if (event.key === 'Escape') setLayersOpen(false) }}>
        <Button variant="ghost" size="xs" aria-label="Plan layers" aria-expanded={layersOpen} aria-haspopup="true" onClick={() => setLayersOpen((open) => !open)}><Layers size={14} />Layers</Button>
        {layersOpen && <><div className="viewer-layers-backdrop" onClick={() => setLayersOpen(false)} /><div className="viewer-layers-card" role="dialog" aria-label="Plan layers"><p className="viewer-layers-title">Show on drawing</p><PlanLayerChips items={planItems} shown={layers.shown} onToggle={layers.toggle} /></div></>}
      </div>}
      {mode === '2d' && <Button variant="ghost" size="icon-sm" aria-label="Measure distance on the drawing" title={mPerPx ? 'Measure: click two points (double-click for an area)' : 'Measure (no scale on this drawing)'} aria-pressed={!!measure.mode} disabled={!image} onClick={() => { if (measure.mode) measure.stop(); else { chooseTool('pan'); setSelectedItem(null); measure.start('distance') } }}><Ruler size={16} /></Button>}
      <div className="viewer-markup-tools">
        <Button variant="ghost" size="xs" aria-label="Show drawing view regions" aria-pressed={showViews} onClick={() => setShowViews((shown) => !shown)}>Views</Button>
        <SymbolMarkupTools markup={markup} disabled={!image} onActivate={() => { setTool('pan'); setSelectedItem(null); setSpecOpen(false) }} />
        <Button variant="ghost" size="icon-sm" aria-label="Search sheet" aria-expanded={searchOpen} aria-controls="viewer-sheet-search" onClick={(event) => { searchTrigger.current = event.currentTarget; if (searchOpen) closeSearch(); else setSearchOpen(true) }}><Search size={16} /></Button>
        <Button variant="ghost" size="icon-sm" aria-label="Highlight marker" aria-pressed={tool === 'marker'} disabled={!image} onClick={() => { markup.cancel(); chooseTool('marker') }}><Highlighter size={16} /></Button>
        <Button variant="ghost" size="icon-sm" aria-label="Pen annotations" aria-pressed={tool === 'pen'} disabled={!image} onClick={() => { markup.cancel(); chooseTool('pen') }}><PenLine size={16} /></Button>
      </div>
      <Button className="viewer-download" variant="ghost" size="icon-sm" aria-label="Download original source" disabled={downloading} onClick={() => void download()}><Download size={16} /></Button>
      <span className="viewer-toolbar-divider" />
      <div className="viewer-zoom-controls">
        <Button variant="ghost" size="icon" aria-label="Zoom out" disabled={!image} onClick={() => zoom(1 / 1.25)}><Minus size={16} /></Button>
        <span aria-label="Zoom level">{Math.round(view.scale / fittedScale * 100)}%</span>
        <Button variant="ghost" size="icon" aria-label="Zoom in" disabled={!image} onClick={() => zoom(1.25)}><Plus size={16} /></Button>
      </div>
    </div>
    {mode === '2d' && searchOpen && <div id="viewer-sheet-search" className="viewer-sheet-search" role="search" aria-label="Find text on sheet">
      <input autoFocus type="search" aria-label="Find on sheet" placeholder="Find text on this sheet…" value={query} onChange={(event) => { setQuery(event.target.value); setHitIndex(0) }} onKeyDown={(event) => {
        if (event.key === 'Enter' && hits.length) { event.preventDefault(); setHitIndex((index) => (index + (event.shiftKey ? hits.length - 1 : 1)) % hits.length) }
      }} />
      <span role="status">{textStatus || (query.trim() ? hits.length ? `${hitIndex + 1} of ${hits.length} matches` : 'No matches' : 'Enter text to find')}</span>
      <Button variant="ghost" size="icon-xs" aria-label="Previous match" disabled={!hits.length} onClick={() => setHitIndex((hitIndex + hits.length - 1) % hits.length)}><ChevronLeft size={14} /></Button>
      <Button variant="ghost" size="icon-xs" aria-label="Next match" disabled={!hits.length} onClick={() => setHitIndex((hitIndex + 1) % hits.length)}><ChevronRight size={14} /></Button>
      <Button variant="ghost" size="icon-xs" aria-label="Close sheet search" onClick={closeSearch}><X size={14} /></Button>
    </div>}
    {mode === '2d' && measure.mode && <div className="viewer-annotation-controls viewer-measure-controls" role="status" aria-live="polite">
      <span>{!mPerPx ? 'No scale on this drawing, so distances cannot be measured.' : measure.result?.distanceM != null ? `Distance: ${formatM(measure.result.distanceM)}` : measure.result?.areaM2 != null ? `Area: ${formatM2(measure.result.areaM2)} · perimeter ${formatM(measure.result.perimeterM ?? 0)}` : measure.mode === 'distance' ? 'Click two points to measure (snaps to plan corners) · Esc to cancel' : 'Click the corners, then double-click or press Enter · Esc to cancel'}</span>
      <Button variant="ghost" size="xs" aria-pressed={measure.mode === 'distance'} onClick={() => measure.start('distance')}>Distance</Button>
      <Button variant="ghost" size="xs" aria-pressed={measure.mode === 'area'} onClick={() => measure.start('area')}>Area</Button>
      <Button variant="ghost" size="xs" onClick={measure.stop}>Done</Button>
    </div>}
    {mode === '2d' && (tool !== 'pan' || annotations.marks.length > 0) && <div className="viewer-annotation-controls"><span>{tool === 'marker' ? 'Drag over an item to mark it' : tool === 'pen' ? 'Draw on the sheet' : 'Annotations saved on this device'}</span><Button variant="ghost" size="xs" disabled={!annotations.marks.length} onClick={annotations.undo}>Undo annotation</Button><Button variant="ghost" size="xs" disabled={!annotations.marks.length} onClick={annotations.clear}>Clear page annotations</Button>{tool !== 'pan' && <Button variant="ghost" size="xs" onClick={() => chooseTool('pan')}>Done</Button>}</div>}
    {(downloadError || annotations.warning) && <p className="viewer-tool-error" role="alert">{downloadError || annotations.warning}</p>}
    {mode === '2d' && specCitation && !specOpen && <Button className="viewer-passage-control" variant="ghost" size="sm" onClick={() => setSpecOpen(true)}>Show cited passage</Button>}
    <div className="viewer-item-layout" hidden={mode === '3d'}>
    <div className="drawing-stage" data-tool={tool} data-pickable={hoverPick ? 'true' : undefined} ref={stage} data-testid="drawing-viewport" tabIndex={0} aria-label="Drawing canvas. Drag to pan, scroll or pinch to zoom. Click an item on the plan for its details. Arrow keys pan, plus and minus zoom, zero fits."
      onKeyDown={(event) => {
        if (event.target !== event.currentTarget) return
        const moves: Record<string, Point> = { ArrowLeft: { x: 40, y: 0 }, ArrowRight: { x: -40, y: 0 }, ArrowUp: { x: 0, y: 40 }, ArrowDown: { x: 0, y: -40 } }
        if (moves[event.key]) { event.preventDefault(); const delta = moves[event.key]; setView((previous) => ({ ...previous, x: previous.x + delta.x, y: previous.y + delta.y })) }
        if (event.key === '+' || event.key === '=') { event.preventDefault(); zoom(1.25) }
        if (event.key === '-') { event.preventDefault(); zoom(1 / 1.25) }
        if (event.key === '0' && image) { event.preventDefault(); setView(fitPage(image, viewport)) }
      }}
      onDoubleClick={(event) => { cancelInspect(); if (measure.mode) { if (measure.mode === 'area') measure.close(); return } if (tool === 'pan') zoom(2, pointerPoint(event.clientX, event.clientY)) }}
      onPointerDown={(event) => {
        if (!image || (event.pointerType === 'mouse' && event.button !== 0)) return
        event.currentTarget.setPointerCapture(event.pointerId)
        if (tool !== 'pan') {
          if (drawingPointer.current !== null) return
          const stagePoint = pointerPoint(event.clientX, event.clientY)
          if (stagePoint.x < view.x || stagePoint.y < view.y || stagePoint.x > view.x + image.width * view.scale || stagePoint.y > view.y + image.height * view.scale) return
          const point = pagePoint(event.clientX, event.clientY)
          const mark: Annotation = { id: crypto.randomUUID(), tool, page: citation.page, points: [point, point], width: 2.5 / view.scale }
          drawingPointer.current = event.pointerId; draftRef.current = mark; setDraft(mark); return
        }
        if (!pointers.current.size) { const start = pointerPoint(event.clientX, event.clientY); tapStart.current = { id: event.pointerId, ...start } } else tapStart.current = null
        pointers.current.set(event.pointerId, pointerPoint(event.clientX, event.clientY))
      }}
      onPointerMove={(event) => {
        if (drawingPointer.current === event.pointerId && draftRef.current) {
          const point = pagePoint(event.clientX, event.clientY)
          const mark = draftRef.current
          const next = { ...mark, points: mark.tool === 'marker' ? [mark.points[0], point] : [...mark.points, point] }
          draftRef.current = next; setDraft(next); return
        }
        if (!pointers.current.has(event.pointerId)) {
          if (event.pointerType === 'mouse') {
            if (measure.mode) { const point = rawPagePoint(event.clientX, event.clientY); measure.move(point ? snapPoint(point as Pt, planItems, 8 / Math.max(view.scale, .001)) : null) }
            const next = planItemAt(event.clientX, event.clientY)
            if (next !== hoverPick) setHoverPick(next)
            const at = next ? pointerPoint(event.clientX, event.clientY) : null
            if (!at ? hoverAt !== null : next !== hoverPick || !hoverAt || Math.hypot(at.x - hoverAt.x, at.y - hoverAt.y) > 2) setHoverAt(at)
          }
          return
        }
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
      onPointerUp={(event) => {
        finishAnnotation(event.pointerId, true)
        const start = tapStart.current
        tapStart.current = null
        if (start && start.id === event.pointerId && pointers.current.size === 1) {
          const end = pointerPoint(event.clientX, event.clientY)
          if (Math.hypot(end.x - start.x, end.y - start.y) < 5) {
            const { clientX, clientY } = event
            cancelInspect()
            if (measure.mode) inspectAt(clientX, clientY)
            else inspectTimer.current = window.setTimeout(() => { inspectTimer.current = null; inspectAt(clientX, clientY) }, 220)
          }
        }
        pointers.current.delete(event.pointerId)
      }}
      onPointerLeave={() => { if (hoverPick) setHoverPick(null); if (hoverAt) setHoverAt(null); if (measure.mode) measure.move(null) }}
      onPointerCancel={(event) => { finishAnnotation(event.pointerId, false); pointers.current.delete(event.pointerId) }}
      onLostPointerCapture={(event) => { finishAnnotation(event.pointerId, false); pointers.current.delete(event.pointerId) }}>
      {imageUrl && <div className="drawing-plane" style={{ width: image?.width, height: image?.height, transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})`, visibility: image ? 'visible' : 'hidden' }}>
        <img src={imageUrl} alt={`Drawing: ${doc?.title ?? citation.doc_id}, page ${shownPage}`} draggable={false}
          onLoad={(event) => { setImage({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight }); setShownPage(loadingPage.current) }}
          onError={() => { setImage(null); setError('This page image could not be displayed.') }} />
        {showViews && image && shownPage === citation.page && <ViewRegions docId={citation.doc_id} page={citation.page} width={image.width} height={image.height} scale={view.scale} />}
        {image && shownPage === citation.page && <RoomLabels docId={citation.doc_id} page={citation.page} width={image.width} height={image.height} scale={view.scale} />}
        {image && shownPage === citation.page && <svg className="drawing-evidence" width={image.width} height={image.height} viewBox={`0 0 ${image.width} ${image.height}`} aria-label="Numbered drawing evidence">
          <PlanLayerShapes items={planItems} shown={layers.shown} selectedId={selectedItem?.itemId ?? null} />
          {!highlights.cleared && regions.map((region, index) => {
            const [x, y, right, bottom] = region.bbox
            const labelSize = 22 / view.scale
            const label = region.label
            const tag = tags[region.id]
            const secondaryTag = answer.evidence.scene.commands?.length && tag !== label ? tag : undefined
            const hidden = itemIsHidden(edits, region.id)
            const kind = region.text ? null : kindStyle(region.kind)
            return <g key={region.id} data-kind={kind ? region.kind ?? 'other' : undefined} style={kind ? { '--kind-color': kind.color, '--kind-on': kind.on } as CSSProperties : undefined} className={`evidence-region ${region.text ? 'text-highlight' : ''} ${shownTags.has(region.id) ? '' : 'tag-collapsed'} ${index === active || linked.selected === region.id || linked.hovered === region.id ? 'is-active' : ''} ${hidden ? 'is-hidden' : ''}`} data-testid={`evidence-box-${region.label}`} aria-label={`${region.text ? 'Text source' : 'Box'} ${label}${secondaryTag ? `, ${secondaryTag}` : ''}${hidden ? ', hidden' : ''}`}
              data-item-id={region.id} data-linked={linked.selected === region.id || linked.hovered === region.id ? 'true' : undefined}
              data-hidden={String(hidden)} data-tag={tag}
              role="button" tabIndex={0} aria-haspopup={sheet ? 'dialog' : undefined}
              onPointerDown={(event) => { if (!measure.mode) event.stopPropagation() }}
              onMouseEnter={() => setHover(region.id, '2d')} onMouseLeave={() => setHover(null, '2d')}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); openItem(index, region.id, event.currentTarget) }
              }}
              onClick={(event) => { if (!measure.mode) openItem(index, region.id, event.currentTarget, event) }}>
              <title>{region.text ? citation.quote ?? 'Text source' : region.id}</title>
              <rect x={x} y={y} width={Math.max(0, right - x)} height={Math.max(0, bottom - y)} vectorEffect="non-scaling-stroke" />
              <svg x={x} y={y} width={labelSize * Math.max(1, label.length / 2)} height={labelSize} viewBox={`0 0 ${22 * Math.max(1, label.length / 2)} 22`} overflow="visible"><rect className="evidence-label-bg" width={22 * Math.max(1, label.length / 2)} height="22" rx="5" /><text x={11 * Math.max(1, label.length / 2)} y="15" textAnchor="middle">{label}</text></svg>
              {secondaryTag && <svg className="evidence-secondary-tag" x={x + labelSize * Math.max(1, label.length / 2)} y={y} width={labelSize * Math.max(1, secondaryTag.length / 2)} height={labelSize} viewBox={`0 0 ${22 * Math.max(1, secondaryTag.length / 2)} 22`}><text x="4" y="15">{secondaryTag}</text></svg>}
            </g>
          })}
          {measure.mode && <MeasureLayer mode={measure.mode} points={measure.points} cursor={measure.cursor} mPerPx={mPerPx} scale={view.scale} />}
          {[...new Set([hoverPick, selectedItem?.docId === citation.doc_id ? selectedItem.itemId : null])].map((id) => {
            const item = id ? planById.get(id) : undefined
            if (!item) return null
            const kind = kindStyle(item.kind)
            const [x, y, right, bottom] = item.bbox
            const outline = item.polygon && item.polygon.length >= 3 && item.kind !== 'text'
            return <g key={`pick-${item.id}`} className={`plan-pick ${item.id === selectedItem?.itemId ? 'is-selected' : ''}`} data-testid="plan-pick" data-item-id={item.id} data-kind={item.kind} aria-hidden="true" style={{ '--kind-color': kind.color } as CSSProperties}>
              {outline ? <polygon points={item.polygon!.map(([px, py]) => `${px},${py}`).join(' ')} vectorEffect="non-scaling-stroke" />
                : <rect x={x} y={y} width={Math.max(0, right - x)} height={Math.max(0, bottom - y)} vectorEffect="non-scaling-stroke" />}
            </g>
          })}
          {!highlights.cleared && leaving.map((region) => {
            const [x, y, right, bottom] = region.bbox
            const kind = region.text ? null : kindStyle(region.kind)
            return <g key={`leaving-${region.id}`} className="evidence-region is-leaving" aria-hidden="true" data-testid="evidence-box-leaving" data-kind={kind ? region.kind ?? 'other' : undefined} style={kind ? { '--kind-color': kind.color, '--kind-on': kind.on } as CSSProperties : undefined}>
              <rect x={x} y={y} width={Math.max(0, right - x)} height={Math.max(0, bottom - y)} vectorEffect="non-scaling-stroke" />
            </g>
          })}
          {hits.map((hit, index) => hit.bbox && <g key={`${index}-${hit.text}`} className={`sheet-search-hit ${index === hitIndex ? 'is-current' : ''}`} data-testid="sheet-search-hit" role="button" tabIndex={0} aria-label={`Search match ${index + 1}: ${hit.text}`} onPointerDown={(event) => { if (!measure.mode) event.stopPropagation() }} onClick={() => { if (!measure.mode) setHitIndex(index) }} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setHitIndex(index) } }}>
            <rect x={hit.bbox[0]} y={hit.bbox[1]} width={Math.max(1, hit.bbox[2] - hit.bbox[0])} height={Math.max(1, hit.bbox[3] - hit.bbox[1])} vectorEffect="non-scaling-stroke" />
            <svg x={hit.bbox[0]} y={hit.bbox[1] - 18 / view.scale} width={20 / view.scale} height={18 / view.scale} viewBox="0 0 20 18"><rect width="20" height="18" rx="3" /><text x="10" y="13" textAnchor="middle">{index + 1}</text></svg>
          </g>)}
          <AnnotationLayer marks={annotations.marks} draft={draft} />
        </svg>}
        {image && shownPage === citation.page && <SymbolMarkupLayer markup={markup} image={image} scale={view.scale} />}
      </div>}
      {!highlights.cleared && image && shownPage === citation.page && regions.some((region) => !region.text) && <KindLegend className="kind-legend-2d" kinds={regions.filter((region) => !region.text).map((region) => region.kind)} totals={totalKinds} />}
      {!measure.mode && hoverPick && hoverAt && (() => {
        const item = planById.get(hoverPick)
        return item ? <PlanHoverTip text={planItemSummary(item, mPerPx)} x={hoverAt.x} y={hoverAt.y} containerWidth={viewport.width} containerHeight={viewport.height} /> : null
      })()}
      {error ? <div className="viewer-message"><p role="alert">{error}</p><Button variant="raised" onClick={() => setRetry(retry + 1)}>Try again</Button></div>
        : !image && <p className="viewer-message" role="status">Loading drawing…</p>}
      {image && shownPage === citation.page && (() => {
        const mark = markup.editing ? markup.symbols.find((m) => m.id === markup.editing) : undefined
        const box = mark ? markBox(mark) : markup.selection && 'box' in markup.selection ? markup.selection.box : null
        if (!box) return null
        return <TellStoaBubble key={mark?.id ?? 'new'} box={box as [number, number, number, number]} view={view} stage={viewport} busy={markup.busy} error={markup.error}
          initial={mark ? { name: mark.name, kind: mark.canonical_kind ?? null } : undefined}
          onSave={(name, kind) => mark ? markup.rename(mark.id, name, kind) : markup.mark(name, kind)}
          onDelete={mark ? () => markup.remove(mark.id) : undefined} onClose={markup.cancel} />
      })()}
    </div>
    {calcOpen && answer.reasoning && <ErrorBoundary resetKey={answer.reasoning} fallback={<aside className="viewer-calc-panel" role="alert" data-testid="calc-error"><div className="calc-content"><p>Could not render this calculation.</p><button type="button" onClick={() => setCalcOpen(false)}>Back to the drawing</button></div></aside>}><CalculationPanel reasoning={answer.reasoning} title={doc?.title} docTitle={(id) => id === citation.doc_id && doc?.title ? doc.title : id} onClose={() => setCalcOpen(false)} onFocus={focusCalcItem} /></ErrorBoundary>}
    {markup.open && <SymbolMarkupPanel markup={markup} page={citation.page} onFocus={(box) => { if (image) setView(focusBox(box, viewport, Math.max(fittedScale, Math.min(4, viewport.width / Math.max(128, (box[2] - box[0]) * 6), viewport.height / Math.max(128, (box[3] - box[1]) * 6))))) }} />}
    {specOpen && !calcOpen && specCitation && <SpecPanel citation={specCitation} title={doc?.title ?? citation.doc_id} text={sheetText} onClose={() => setSpecOpen(false)} />}
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
    {overlayOpen && <SheetOverlay key={`${citation.doc_id}-${citation.page}`} baseDocId={citation.doc_id} page={citation.page} initialOverlayDocId={initialOverlayDocId} onAlignment={onOverlayAlignment} onClose={() => setOverlayOpen(false)} />}
  </aside>
}
