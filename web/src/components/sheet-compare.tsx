import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent, type ReactNode } from 'react'
import { Check, Download, GripVertical, Maximize2, Minus, Plus, Sparkles } from 'lucide-react'
import { Button } from './ui'
import {
  FIT_VIEW, OPEN_SEAM_FROM, OPEN_SEAM_TO, boxRect, clampView, easeInOut, fitSheet, lerpView, nudgeSeam, panView, parseHex, regionView,
  seamFromPointer, shortVersion, sheetTransform, stepZoom, thumbLayout, tintMatrix, usableBox, versionDate, zoomAt,
  THUMB_H, THUMB_W, type Bbox, type Size, type View,
} from '../lib/sheet-compare'
import { downloadReadings } from '../lib/sheet-export'
import './sheet-compare.css'

export type SheetMode = 'Plain' | 'Wipe' | 'Overlay'
export type SheetChange = {
  id: string; n: number; kind: 'added' | 'removed' | 'edited'
  /** Region in sheet pixels (same space as `size`). Null when the engine could not place it. */
  bbox: Bbox | null
  text: string
  /** Minor edits (callout labels, linework) sit in a collapsed list under the main readings. */
  small?: boolean
}
export type SheetSide = { label: string; src: string | null }
export type SheetCompareProps = {
  prev: SheetSide
  curr: SheetSide
  /** Size of the sheet image that every bbox is measured in. */
  size: Size
  changes: SheetChange[]
  initialMode?: SheetMode
  /** Show the "Drag to compare" pill when Wipe opens. */
  showHint?: boolean
  onHintDone?: () => void
  /** One quiet line above the readings (counts). */
  summary?: ReactNode
  /** File name stem for Export. */
  exportName?: string
  /** Text shown in the readings pane when there are no changes. */
  emptyText?: string
  /** Fires when the focused change changes (card or box click, Escape). */
  onFocusChange?: (id: string | null) => void
}

const kindWord = { added: 'added', removed: 'removed', edited: 'edited' } as const
const prefersReducedMotion = () => typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
const DEFAULT_VIEWPORT: Size = { w: 499, h: 525 }

/** The small mark next to anything software worked out for the reader. Honest: it does not claim a model was used. */
export function WorkedOutMark({ title = 'Worked out automatically from the files' }: { title?: string }) {
  return <span className="ai-mark" role="img" aria-label={title} title={title}><Sparkles size={10} strokeWidth={2.25} /></span>
}

function Thumb({ src, bbox, size, label }: { src: string | null; bbox: Bbox | null; size: Size; label: string }) {
  const [failed, setFailed] = useState(false)
  useEffect(() => setFailed(false), [src])
  if (!src || !usableBox(bbox, size) || failed) {
    return <div className="sc-thumb sc-thumb-empty" role="img" aria-label={`${label}: not available`}><span>{!src || failed ? 'No image' : 'No location'}</span></div>
  }
  const t = thumbLayout(bbox, size, { w: THUMB_W, h: THUMB_H })
  return <div className="sc-thumb" role="img" aria-label={label} data-zoom={Math.round(t.zoom)}>
    <img src={src} alt="" draggable={false} decoding="async" onError={() => setFailed(true)} style={{ width: t.width, height: t.height, left: t.left, top: t.top }} />
  </div>
}

export function SheetCompare({ prev, curr, size, changes, initialMode = 'Wipe', showHint = true, onHintDone, summary, exportName = 'changes', emptyText = 'No differences were found between these versions.', onFocusChange }: SheetCompareProps) {
  const uid = useId().replace(/[^a-zA-Z0-9]/g, '')
  const canvas = useRef<HTMLDivElement>(null)
  const root = useRef<HTMLDivElement>(null)
  const [mode, setMode] = useState<SheetMode>(initialMode)
  const [boxes, setBoxes] = useState(true)
  const [opacity, setOpacity] = useState(50)
  const [viewport, setViewport] = useState<Size>(DEFAULT_VIEWPORT)
  const [view, setView] = useState<View>(FIT_VIEW)
  const [seam, setSeam] = useState(initialMode === 'Wipe' ? OPEN_SEAM_FROM : OPEN_SEAM_TO)
  const [moving, setMoving] = useState(false)
  const [focused, setFocused] = useState<string | null>(null)
  const [hint, setHint] = useState(false)
  const [status, setStatus] = useState<Record<string, 'ok' | 'error'>>({})
  const [panning, setPanning] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState('')
  const viewRef = useRef(view); viewRef.current = view
  const tween = useRef(0)
  const opened = useRef(false)
  const keyTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const sizeOk = size.w > 0 && size.h > 0
  const fit = useMemo(() => fitSheet(viewport, size), [viewport, size])
  const state = (side: SheetSide): 'ok' | 'error' | 'loading' => !side.src ? 'error' : status[side.src] ?? 'loading'
  const prevState = state(prev), currState = state(curr)
  const ready = prevState !== 'loading' && currState !== 'loading'
  const tint = useMemo(() => {
    const read = (name: string, fallback: [number, number, number]) => typeof document === 'undefined' ? fallback : parseHex(getComputedStyle(document.documentElement).getPropertyValue(name), fallback)
    return { prev: tintMatrix(read('--change-removed', [0.792, 0.282, 0.165])), curr: tintMatrix(read('--change-added', [0.212, 0.486, 0.282])) }
  }, [])

  // Measure the canvas.
  useLayoutEffect(() => {
    const el = canvas.current
    if (!el) return
    const measure = () => { const r = el.getBoundingClientRect(); if (r.width > 0 && r.height > 0) setViewport((old) => old.w === r.width && old.h === r.height ? old : { w: r.width, h: r.height }) }
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(measure); observer.observe(el)
    return () => observer.disconnect()
  }, [])

  // Animate the view (zoom to a region, fit, zoom buttons). Everything that depends on the view moves together.
  const animateTo = useCallback((target: View, ms = 450) => {
    cancelAnimationFrame(tween.current)
    const goal = clampView(target)
    if (ms <= 0 || prefersReducedMotion()) { setView(goal); return }
    const from = viewRef.current, start = performance.now()
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / ms)
      setView(lerpView(from, goal, easeInOut(t)))
      if (t < 1) tween.current = requestAnimationFrame(step)
    }
    tween.current = requestAnimationFrame(step)
  }, [])
  useEffect(() => () => { cancelAnimationFrame(tween.current); if (keyTimer.current) clearTimeout(keyTimer.current) }, [])

  // Wipe opens closed and slides to the middle once the sheets are ready, then idles.
  useEffect(() => {
    if (mode !== 'Wipe' || !ready || opened.current || !sizeOk) return
    opened.current = true
    if (prefersReducedMotion()) { setSeam(OPEN_SEAM_TO); return }
    setSeam(OPEN_SEAM_FROM)
    let inner = 0, reached = false
    const outer = requestAnimationFrame(() => { inner = requestAnimationFrame(() => { reached = true; setSeam(OPEN_SEAM_TO) }) })
    return () => { cancelAnimationFrame(outer); cancelAnimationFrame(inner); if (!reached) opened.current = false }
  }, [mode, ready, sizeOk])
  useEffect(() => {
    if (mode !== 'Wipe' || !ready || !showHint) { setHint(false); return }
    setHint(true)
    const timer = setTimeout(() => { setHint(false); onHintDone?.() }, 4500)
    return () => clearTimeout(timer)
  }, [mode, ready, showHint]) // eslint-disable-line react-hooks/exhaustive-deps
  const dismissHint = () => { if (hint) { setHint(false); onHintDone?.() } }

  const focusChange = useCallback((id: string | null) => {
    dismissHint(); setFocused(id); onFocusChange?.(id)
    const change = id ? changes.find((c) => c.id === id) : null
    if (change && usableBox(change.bbox, size)) animateTo(regionView(change.bbox, size, fit, viewport))
    else if (!id) animateTo(FIT_VIEW)
  }, [animateTo, changes, fit, onFocusChange, size, viewport])
  // A new set of changes (another pair of versions) starts fresh.
  useEffect(() => { setFocused(null); setView(FIT_VIEW) }, [changes])
  useEffect(() => {
    if (!focused) return
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') focusChange(null) }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [focused, focusChange])

  const zoomBy = (direction: 1 | -1) => {
    const next = stepZoom(viewRef.current.s * 100, direction) / 100
    animateTo(zoomAt(viewRef.current, next, { x: viewport.w / 2, y: viewport.h / 2 }, fit, viewport), 250)
  }
  const fitView = () => { setFocused(null); onFocusChange?.(null); animateTo(FIT_VIEW) }

  // Wheel: ctrl/cmd (pinch) zooms around the pointer; otherwise a zoomed sheet pans. A fitted sheet lets the page scroll.
  useEffect(() => {
    const el = canvas.current
    if (!el) return
    const onWheel = (event: WheelEvent) => {
      const bounds = el.getBoundingClientRect()
      const current = viewRef.current
      if (event.ctrlKey || event.metaKey) {
        event.preventDefault(); cancelAnimationFrame(tween.current)
        setView(zoomAt(current, current.s * Math.exp(-event.deltaY * 0.01), { x: event.clientX - bounds.left, y: event.clientY - bounds.top }, fit, viewport))
      } else if (current.s > 1.001) {
        event.preventDefault(); cancelAnimationFrame(tween.current)
        setView(panView(current, -event.deltaX, -event.deltaY, fit))
      }
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [fit, viewport])

  // Drag the zoomed sheet.
  const pan = useRef<{ x: number; y: number; id: number } | null>(null)
  const onCanvasDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (viewRef.current.s <= 1.001 || (event.pointerType === 'mouse' && event.button !== 0)) return
    if ((event.target as HTMLElement).closest('.sc-box, .wipe-seam, button')) return
    cancelAnimationFrame(tween.current)
    pan.current = { x: event.clientX, y: event.clientY, id: event.pointerId }
    event.currentTarget.setPointerCapture(event.pointerId); setPanning(true)
  }
  const onCanvasMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!pan.current || pan.current.id !== event.pointerId) return
    const dx = event.clientX - pan.current.x, dy = event.clientY - pan.current.y
    pan.current = { ...pan.current, x: event.clientX, y: event.clientY }
    setView((old) => panView(old, dx, dy, fit))
  }
  const endPan = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (pan.current?.id === event.pointerId && event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
    pan.current = null; setPanning(false)
  }

  // The seam: mouse, touch and keyboard.
  const seamDrag = useRef(false)
  const seamAt = (clientX: number) => { const b = canvas.current?.getBoundingClientRect(); if (b) setSeam(seamFromPointer(clientX, b.left, b.width)) }
  const onSeamDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.pointerType === 'mouse' && event.button !== 0) return
    event.preventDefault(); event.stopPropagation()
    event.currentTarget.setPointerCapture(event.pointerId)
    seamDrag.current = true; setMoving(true); dismissHint(); seamAt(event.clientX)
    ;(event.currentTarget.querySelector('[role=slider]') as HTMLElement | null)?.focus({ preventScroll: true })
  }
  const onSeamMove = (event: ReactPointerEvent<HTMLDivElement>) => { if (seamDrag.current) seamAt(event.clientX) }
  const onSeamUp = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
    seamDrag.current = false; setMoving(false)
  }
  const onSeamKey = (event: ReactKeyboardEvent<HTMLElement>) => {
    const next = nudgeSeam(seam, event.key, event.shiftKey)
    if (next == null) return
    event.preventDefault(); dismissHint()
    setMoving(true); setSeam(next)
    if (keyTimer.current) clearTimeout(keyTimer.current)
    keyTimer.current = setTimeout(() => setMoving(false), 250)
  }

  const onRootKey = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement
    if (target.closest('input, select, textarea') || target.getAttribute('role') === 'slider') return
    if (event.key === '+' || event.key === '=') { event.preventDefault(); zoomBy(1) }
    else if (event.key === '-' || event.key === '_') { event.preventDefault(); zoomBy(-1) }
    else if (event.key === '0') { event.preventDefault(); fitView() }
  }

  const doExport = async () => {
    if (exporting) return
    setExporting(true); setExportError('')
    try {
      await downloadReadings({ name: exportName, prev: { label: prev.label, src: prev.src }, curr: { label: curr.label, src: curr.src }, size, changes })
    } catch (error) { setExportError(error instanceof Error ? error.message : 'The list could not be exported.') }
    finally { setExporting(false) }
  }

  const sheetStyle = (): CSSProperties => {
    const t = sheetTransform(view, fit, viewport)
    return { width: fit.w, height: fit.h, transform: `translate(${t.x}px, ${t.y}px) scale(${t.scale})` }
  }
  const missing = (side: SheetSide, which: 'previous' | 'latest') => <div className="sc-missing" role="status">
    <strong>{shortVersion(side.label)}</strong><span>{side.src ? `The ${which} sheet image could not be loaded.` : `No sheet image is stored for the ${which} version.`}</span>
  </div>
  const main = changes.filter((c) => !c.small), minor = changes.filter((c) => c.small)
  const counts = { added: changes.filter((c) => c.kind === 'added').length, removed: changes.filter((c) => c.kind === 'removed').length, edited: changes.filter((c) => c.kind === 'edited').length }
  const bothFailed = prevState === 'error' && currState === 'error'
  const shownBoxes = boxes && sizeOk && fit.w > 0 && !bothFailed

  const card = (c: SheetChange, compact = false) => <article key={c.id} className={`sc-card ${c.kind}${compact ? ' compact' : ''}`} data-change-id={c.id} data-active={c.id === focused || undefined} role="button" tabIndex={0} aria-pressed={c.id === focused}
    onClick={() => focusChange(c.id === focused ? null : c.id)}
    onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); focusChange(c.id === focused ? null : c.id) } }}>
    <span className="reading-number">{c.n}</span>
    {!compact && <div className="sc-thumbs"><Thumb src={prev.src} bbox={c.bbox} size={size} label={`Change ${c.n} before`} /><Thumb src={curr.src} bbox={c.bbox} size={size} label={`Change ${c.n} after`} /></div>}
    <div className="sc-card-text"><WorkedOutMark /><p>{c.text}</p></div>
  </article>

  return <div ref={root} className="comparison-box sheet-compare" aria-label="Compare revisions" data-mode={mode} onKeyDown={onRootKey}>
    <div className="comparison-toolbar">
      <div className="compare-segments" role="group" aria-label="Comparison mode">{(['Plain', 'Wipe', 'Overlay'] as const).map((item) => <button type="button" key={item} aria-pressed={mode === item} onClick={() => { dismissHint(); setMode(item) }}>{item}</button>)}</div>
      <label className="change-boxes"><input type="checkbox" checked={boxes} onChange={(event) => setBoxes(event.target.checked)} /><span aria-hidden>{boxes && <Check size={12} strokeWidth={3} />}</span>Change boxes</label>
      {mode === 'Overlay' && <label className="sc-opacity"><span>Latest</span><input type="range" min="0" max="100" value={opacity} aria-label="Overlay opacity" onChange={(event) => setOpacity(Number(event.target.value))} /><output>{opacity}%</output></label>}
      <span className="toolbar-spacer" />
      <Button variant="ghost" size="icon" aria-label="Zoom out comparison" onClick={() => zoomBy(-1)}><Minus size={14} /></Button>
      <span className="comparison-zoom" aria-live="off">{Math.round(view.s * 100)}%</span>
      <Button variant="ghost" size="icon" aria-label="Zoom in comparison" onClick={() => zoomBy(1)}><Plus size={14} /></Button>
      <Button variant="ghost" size="icon" aria-label="Fit comparison" className="sc-fit" onClick={fitView}><Maximize2 size={14} /></Button>
    </div>
    <div className="comparison-content">
      <div ref={canvas} className={`comparison-canvas sc-canvas${view.s > 1.001 ? ' zoomed' : ''}`} data-mode={mode} data-moving={moving || undefined} data-panning={panning || undefined} data-focused={focused || undefined}
        style={{ '--seam': `${seam}%` } as CSSProperties} onPointerDown={onCanvasDown} onPointerMove={onCanvasMove} onPointerUp={endPan} onPointerCancel={endPan} onDoubleClick={(event) => { if (!(event.target as HTMLElement).closest('.sc-box, .wipe-seam')) fitView() }}>
        <svg className="sc-defs" width="0" height="0" aria-hidden focusable="false"><defs>
          <filter id={`${uid}-prev`} colorInterpolationFilters="sRGB"><feColorMatrix type="matrix" values={tint.prev} /></filter>
          <filter id={`${uid}-curr`} colorInterpolationFilters="sRGB"><feColorMatrix type="matrix" values={tint.curr} /></filter>
        </defs></svg>
        {sizeOk && !bothFailed && <>
          <div className="sc-layer sc-prev" aria-hidden={mode === 'Plain'}>
            {prevState === 'error' ? missing(prev, 'previous') : <div className="sc-sheet" style={sheetStyle()}>
              <img src={prev.src!} alt="Previous revision" draggable={false} decoding="async" style={mode === 'Overlay' ? { filter: `url(#${uid}-prev)` } : undefined}
                ref={(img) => { if (img?.complete && img.naturalWidth > 0 && !status[prev.src!]) setStatus((old) => ({ ...old, [prev.src!]: 'ok' })) }}
                onLoad={() => setStatus((old) => ({ ...old, [prev.src!]: 'ok' }))} onError={() => setStatus((old) => ({ ...old, [prev.src!]: 'error' }))} />
            </div>}
          </div>
          <div className="sc-layer sc-curr" style={mode === 'Overlay' ? { opacity: opacity / 100 } : undefined}>
            {currState === 'error' ? missing(curr, 'latest') : <div className="sc-sheet" style={sheetStyle()}>
              <img src={curr.src!} alt="Latest revision" draggable={false} decoding="async" style={mode === 'Overlay' ? { filter: `url(#${uid}-curr)` } : undefined}
                ref={(img) => { if (img?.complete && img.naturalWidth > 0 && !status[curr.src!]) setStatus((old) => ({ ...old, [curr.src!]: 'ok' })) }}
                onLoad={() => setStatus((old) => ({ ...old, [curr.src!]: 'ok' }))} onError={() => setStatus((old) => ({ ...old, [curr.src!]: 'error' }))} />
            </div>}
          </div>
        </>}
        {shownBoxes && <div className="sc-boxes">{changes.map((c) => {
          if (!usableBox(c.bbox, size)) return null
          const r = boxRect(c.bbox, size, view, fit, viewport)
          return <button type="button" key={c.id} className={`sc-box change-region ${c.kind}`} data-change-id={c.id} data-active={c.id === focused || undefined} aria-pressed={c.id === focused}
            aria-label={`Change ${c.n} (${kindWord[c.kind]}): ${c.text}`} style={{ left: r.left, top: r.top, width: r.width, height: r.height }}
            onClick={(event) => { event.stopPropagation(); focusChange(c.id === focused ? null : c.id) }}><b>{c.n}</b></button>
        })}</div>}
        {mode === 'Wipe' && sizeOk && !bothFailed && <>
          <div className="wipe-labels" aria-hidden>
            <span className="wipe-label-a" title={versionDate(prev.label) || undefined}>{shortVersion(prev.label)}</span>
            <span className="wipe-label-b" title={versionDate(curr.label) || undefined}>{shortVersion(curr.label)} · Latest</span>
          </div>
          <div className="wipe-seam" onPointerDown={onSeamDown} onPointerMove={onSeamMove} onPointerUp={onSeamUp} onPointerCancel={onSeamUp}>
            <span className="wipe-hit" />
            <span className="wipe-line" />
            <span className="wipe-grip" role="slider" tabIndex={0} aria-label="Wipe position" aria-orientation="horizontal" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(seam)} aria-valuetext={`${Math.round(seam)} percent`} onKeyDown={onSeamKey}><GripVertical size={16} /></span>
            <span className="wipe-hint" data-flip={seam > 65 || undefined} data-visible={hint || undefined} aria-hidden={!hint}>Drag to compare</span>
          </div>
        </>}
        {!ready && sizeOk && !bothFailed && <p className="sc-message sc-loading" role="status">Loading both sheets…</p>}
        {!sizeOk && <p className="sc-message" role="status">These versions have no sheet size on record, so the drawings cannot be shown side by side. The changes are listed on the right.</p>}
        {bothFailed && sizeOk && <p className="sc-message" role="status">Neither sheet image could be loaded. The changes are still listed on the right.</p>}
      </div>
      <aside className="comparison-readings" aria-label="Change readings">
        <header><span className="sc-head-a" title={versionDate(prev.label) || undefined}>{shortVersion(prev.label)}</span><span className="sc-head-b" title={versionDate(curr.label) || undefined}>{shortVersion(curr.label)}</span>
          <button type="button" className="sc-export" onClick={doExport} disabled={exporting || !changes.length}><Download size={12} />{exporting ? 'Exporting…' : 'Export'}</button></header>
        {exportError && <p className="error-message" role="alert">{exportError}</p>}
        <div className="sc-readings-body">
          {summary && <div className="changes-plain-summary">{summary}</div>}
          {changes.length > 0 && <p className="sc-key" aria-label="Box colours"><i className="added" />{counts.added} added<i className="removed" />{counts.removed} removed<i className="edited" />{counts.edited} edited</p>}
          {main.map((c) => card(c))}
          {minor.length > 0 && <details className="cmp-small" open={main.length === 0 || undefined}><summary>Minor edits ({minor.length})</summary>{minor.map((c) => card(c, main.length > 0))}</details>}
          {!changes.length && <p className="sc-empty" role="status">{emptyText}</p>}
        </div>
      </aside>
    </div>
  </div>
}
