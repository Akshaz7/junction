import { useEffect, useRef, useState, type PointerEvent } from 'react'
import { MapPin, PenLine, X } from 'lucide-react'
import type { Bbox } from '../../lib/types'
import type { Point, Size } from '../../lib/page-transform'
import { Button } from '../ui'
import { markupRequest, type MarkupData, type MarkupPin, type TaughtSymbol } from './markup-api'
import { kindLabel } from './taught-kinds'
import './symbol-markup.css'

type Selection = { box: Bbox } | { point: Point }
export function useSymbolMarkup(docId: string, page: number) {
  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState<'label' | 'pin' | null>(null)
  const [data, setData] = useState<MarkupData>({ symbols: [], pins: [], suggestions: [] })
  const [selection, setSelection] = useState<Selection | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [editing, setEditing] = useState<string | null>(null)
  const generation = useRef(0)
  const controller = useRef<AbortController | null>(null)
  useEffect(() => {
    generation.current++
    setData({ symbols: [], pins: [], suggestions: [] }); setSelection(null); setMode(null); setOpen(false); setLoaded(false); setError(''); setBusy(false); setEditing(null)
    const abort = new AbortController()
    markupRequest<MarkupPin[]>(docId, '/pins', { signal: abort.signal }).then((pins) => {
      if (!abort.signal.aborted && Array.isArray(pins)) setData((d) => ({ ...d, pins }))
    }).catch(() => {}) // The notes panel provides the retry/error state if storage is unavailable.
    return () => abort.abort()
  }, [docId, page])
  useEffect(() => {
    if (loaded) return
    const abort = new AbortController()
    markupRequest<MarkupData>(docId, `?page=${page}`, { signal: abort.signal }).then((value) => {
      if (!abort.signal.aborted) { setData({ symbols: [], pins: [], suggestions: [], ...(value && typeof value === 'object' ? value : {}) }); setLoaded(true); setError('') }
    }).catch((err: unknown) => { if (!abort.signal.aborted) setError(err instanceof Error ? err.message : 'Labels could not be loaded.') })
    return () => abort.abort()
  }, [loaded, docId, page])
  useEffect(() => () => controller.current?.abort(), [])
  async function mutate(action: (signal: AbortSignal) => Promise<void>) {
    if (busy) return
    const current = generation.current
    const abort = new AbortController(); controller.current = abort
    setBusy(true); setError('')
    try { await action(abort.signal) } catch (err) { if (generation.current === current && !abort.signal.aborted) setError(err instanceof Error ? err.message : 'Could not save. Try again.') }
    finally { if (generation.current === current) setBusy(false) }
  }
  const symbols = data.symbols.filter((s) => s.page === page)
  return { open, mode, data, selection, error, busy, loaded, symbols, editing, page,
    toggle(next: 'label' | 'pin') { setOpen(true); setSelection(null); setEditing(null); setMode((old) => old === next ? null : next) },
    close() { setOpen(false); setMode(null); setSelection(null); setEditing(null) },
    showNotes() { setOpen(true); setMode(null); setSelection(null); setEditing(null) },
    select(value: Selection) { setSelection(value); setEditing(null); setMode(null) },
    cancel() { setSelection(null); setEditing(null); setMode(null) },
    edit(id: string | null) { setEditing(id); setSelection(null); setMode(null) },
    reload() { setLoaded(false); setError(''); setOpen(false); requestAnimationFrame(() => setOpen(true)) },
    /** Saves the highlighted box as one item of the given kind. No matching of similar marks. */
    mark(name: string, kind: string | null) {
      if (!selection || !('box' in selection)) return
      const current = generation.current
      void mutate(async (signal) => {
        const saved = await markupRequest<TaughtSymbol>(docId, '/symbols', { method: 'POST', signal, body: JSON.stringify({ page, box: selection.box, name, note: '', ...(kind ? { canonical_kind: kind } : {}) }) })
        if (generation.current !== current) return
        setData((d) => ({ ...d, symbols: [...d.symbols, saved] })); setSelection(null)
      })
    },
    rename(id: string, name: string, kind: string | null) {
      const current = generation.current
      void mutate(async (signal) => {
        const saved = await markupRequest<TaughtSymbol>(docId, `/symbols/${id}`, { method: 'PATCH', signal, body: JSON.stringify({ name, canonical_kind: kind }) })
        if (generation.current !== current) return
        setData((d) => ({ ...d, symbols: d.symbols.map((s) => s.id === id ? { ...s, ...saved } : s) })); setEditing(null)
      })
    },
    remove(id: string) {
      const current = generation.current
      void mutate(async (signal) => {
        await markupRequest<void>(docId, `/symbols/${id}`, { method: 'DELETE', signal })
        if (generation.current !== current) return
        setData((d) => ({ ...d, symbols: d.symbols.filter((s) => s.id !== id) })); setEditing(null)
      })
    },
    pin(note: string) {
      if (!selection || !('point' in selection)) return
      const current = generation.current
      void mutate(async (signal) => {
        await markupRequest<MarkupPin>(docId, '/pins', { method: 'POST', signal, body: JSON.stringify({ page, ...selection.point, note }) })
        const pins = await markupRequest<MarkupPin[]>(docId, '/pins', { signal })
        if (generation.current !== current) return
        setData((d) => ({ ...d, pins })); setSelection(null)
      })
    },
    removePin(id: string) {
      const current = generation.current
      void mutate(async (signal) => {
        await markupRequest<void>(docId, `/pins/${id}`, { method: 'DELETE', signal })
        const pins = await markupRequest<MarkupPin[]>(docId, '/pins', { signal })
        if (generation.current === current) setData((d) => ({ ...d, pins }))
      })
    },
  }
}
/** The box a saved mark covers: its single confirmed match, else the box that was highlighted. */
export const markBox = (s: TaughtSymbol): Bbox => s.matches?.[0]?.bbox ?? s.template_bbox
export const markName = (s: TaughtSymbol) => kindLabel(s.canonical_kind, s.name)
type Markup = ReturnType<typeof useSymbolMarkup>
export function SymbolMarkupTools({ markup, disabled, onActivate }: { markup: Markup; disabled: boolean; onActivate: () => void }) {
  return <Button variant="ghost" size="icon-sm" aria-label="Place a note pin" aria-pressed={markup.mode === 'pin'} disabled={disabled || markup.busy} onClick={() => { onActivate(); markup.toggle('pin') }}><MapPin size={16} /></Button>
}

export function SymbolMarkupLayer({ markup, image, scale }: { markup: Markup; image: Size; scale: number }) {
  const drag = useRef<{ start: Point; id: number } | null>(null)
  const [draft, setDraft] = useState<Bbox | null>(null)
  useEffect(() => { drag.current = null; setDraft(null) }, [markup.mode])
  function point(event: PointerEvent<SVGSVGElement>): Point {
    const r = event.currentTarget.getBoundingClientRect()
    return { x: Math.max(0, Math.min(image.width, (event.clientX - r.left) / scale)), y: Math.max(0, Math.min(image.height, (event.clientY - r.top) / scale)) }
  }
  const rect = (a: Point, b: Point): Bbox => [Math.min(a.x, b.x), Math.min(a.y, b.y), Math.max(a.x, b.x), Math.max(a.y, b.y)]
  const box = draft ?? (markup.selection && 'box' in markup.selection ? markup.selection.box : null)
  return <svg className={`symbol-markup-layer ${markup.mode ? 'is-drawing' : ''}`} width={image.width} height={image.height} viewBox={`0 0 ${image.width} ${image.height}`} aria-label="Saved symbol boxes and note pins"
    onPointerDown={(event) => {
      if (!markup.mode || event.button !== 0 || drag.current) return
      event.stopPropagation(); event.currentTarget.setPointerCapture(event.pointerId)
      drag.current = { start: point(event), id: event.pointerId }; setDraft(null)
    }}
    onPointerMove={(event) => { if (drag.current?.id === event.pointerId) { event.stopPropagation(); if (markup.mode === 'label') setDraft(rect(drag.current.start, point(event))) } }}
    onPointerUp={(event) => {
      if (drag.current?.id !== event.pointerId) return
      event.stopPropagation()
      const start = drag.current.start; drag.current = null; setDraft(null)
      if (markup.mode === 'pin') markup.select({ point: point(event) })
      else { const box = rect(start, point(event)); if (box[2] - box[0] >= 4 && box[3] - box[1] >= 4) markup.select({ box }) }
    }} onPointerCancel={() => { drag.current = null; setDraft(null) }} onLostPointerCapture={() => { drag.current = null; setDraft(null) }}>
    {markup.symbols.map((m) => { const b = markBox(m), label = m.canonical_kind ? kindLabel(m.canonical_kind, m.name) : m.name, w = Math.max(32, label.length * 8 + 16)
      return <g key={m.id} className={`taught-mark ${markup.editing === m.id ? 'is-active' : ''}`} role="button" tabIndex={0} aria-label={`Marked as ${label}. Press Enter to rename or delete.`}
        onPointerDown={(e) => { if (!markup.mode) e.stopPropagation() }} onClick={() => markup.edit(m.id)} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); markup.edit(m.id) } }}>
        <rect x={b[0]} y={b[1]} width={b[2] - b[0]} height={b[3] - b[1]} vectorEffect="non-scaling-stroke" />
        <svg x={b[0]} y={b[1] - 23 / scale} width={w / scale} height={22 / scale} viewBox={`0 0 ${w} 22`} overflow="visible"><rect width={w} height="22" rx="11" /><text x={w / 2} y="15.5" textAnchor="middle">{label}</text></svg>
      </g> })}
    {markup.data.pins.filter((p) => p.page === markup.page).map((pin) => <g key={pin.id} className="markup-note-pin" role="button" tabIndex={0} aria-label={`Pin ${pin.n}: ${pin.note}`} onPointerDown={(e) => { if (!markup.mode) e.stopPropagation() }} onClick={markup.showNotes} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); markup.showNotes() } }} transform={`translate(${pin.x},${pin.y}) scale(${1 / scale})`}><title>{pin.note}</title><circle r="10" /><text y="4" textAnchor="middle">{pin.n}</text></g>)}
    {box && <rect className="symbol-selection" x={box[0]} y={box[1]} width={box[2] - box[0]} height={box[3] - box[1]} vectorEffect="non-scaling-stroke" />}
    {markup.selection && 'point' in markup.selection && <circle className="symbol-selection" cx={markup.selection.point.x} cy={markup.selection.point.y} r={8 / scale} vectorEffect="non-scaling-stroke" />}
  </svg>
}

export function SymbolMarkupPanel({ markup, page, onFocus }: { markup: Markup; page: number; onFocus: (box: Bbox) => void }) {
  const [note, setNote] = useState('')
  useEffect(() => { setNote('') }, [markup.selection])
  const marks = markup.symbols
  const counts = new Map<string, number>()
  for (const m of marks) counts.set(markName(m), (counts.get(markName(m)) ?? 0) + 1)
  return <section className="symbol-markup-panel" tabIndex={-1} aria-label="Marks and notes">
    <header><strong>Marks & notes</strong><Button variant="ghost" size="icon-xs" aria-label="Close marks and notes" onClick={markup.close}><X size={16} /></Button></header>
    {markup.error && <p role="alert">{markup.error} {!markup.loaded && <button onClick={markup.reload}>Retry</button>}</p>}
    {!markup.loaded && !markup.error && <p role="status">Loading saved marks…</p>}
    {markup.mode && <p role="status">{markup.mode === 'label' ? 'Drag a box around one item, then tell Stoa what it is. Zoom in for dense sheets.' : 'Click the drawing to place a numbered note.'}</p>}
    {markup.selection && 'point' in markup.selection && <form onSubmit={(event) => { event.preventDefault(); markup.pin(note.trim()) }}>
      <label>Pin note<textarea autoFocus required value={note} maxLength={4000} onChange={(e) => setNote(e.target.value)} /></label>
      <Button type="submit" variant="primary" size="sm" disabled={markup.busy || !markup.loaded || !note.trim()}>Save pin</Button><Button size="sm" variant="ghost" disabled={markup.busy} onClick={markup.cancel}>Cancel</Button>
    </form>}
    <h3>Marked items · Page {page}</h3>
    {marks.length === 0 ? <p className="markup-caution">Nothing marked yet. Use Mark, drag a box around one item and say what it is.</p>
      : <><p className="markup-count">{[...counts].map(([name, n]) => `${n} ${name}`).join(' · ')}</p>
        <ol className="markup-pin-list">{marks.map((m) => <li key={m.id}><button onClick={() => { onFocus(markBox(m)); markup.edit(m.id) }}>{markName(m)}{m.canonical_kind && m.name.toLowerCase() !== markName(m).toLowerCase() ? ` (${m.name})` : ''}</button><Button variant="ghost" size="xs" disabled={markup.busy} onClick={() => markup.remove(m.id)}>Delete</Button></li>)}</ol></>}
    <h3>Note pins · Page {page}</h3><p>Saved notes are included in Export report.</p>
    <ol className="markup-pin-list">{markup.data.pins.filter((p) => p.page === page).map((pin) => <li key={pin.id}><button onClick={() => onFocus([pin.x - 30, pin.y - 30, pin.x + 30, pin.y + 30])}>Pin {pin.n}: {pin.note}</button><Button variant="ghost" size="xs" disabled={markup.busy} onClick={() => markup.removePin(pin.id)}>Delete</Button></li>)}</ol>
  </section>
}
