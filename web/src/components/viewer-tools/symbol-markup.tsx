import { useEffect, useId, useRef, useState, type PointerEvent } from 'react'
import { MapPin, PenLine, X } from 'lucide-react'
import type { Bbox } from '../../lib/types'
import type { Point, Size } from '../../lib/page-transform'
import { Button } from '../ui'
import { markupRequest, type MarkupData, type MarkupPin, type MatchStatus, type TaughtSymbol } from './markup-api'
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
  const [symbolId, setSymbolId] = useState('')
  const [index, setIndex] = useState(0)
  const generation = useRef(0)
  const controller = useRef<AbortController | null>(null)
  useEffect(() => {
    generation.current++
    setData({ symbols: [], pins: [], suggestions: [] }); setSelection(null); setMode(null); setOpen(false); setLoaded(false); setError(''); setBusy(false); setSymbolId(''); setIndex(0)
    const abort = new AbortController()
    markupRequest<MarkupPin[]>(docId, '/pins', { signal: abort.signal }).then((pins) => {
      if (!abort.signal.aborted && Array.isArray(pins)) setData((d) => ({ ...d, pins }))
    }).catch(() => {}) // The notes panel provides the retry/error state if storage is unavailable.
    return () => abort.abort()
  }, [docId, page])
  useEffect(() => {
    if (!open || loaded) return
    const abort = new AbortController()
    markupRequest<MarkupData>(docId, `?page=${page}`, { signal: abort.signal }).then((value) => {
      if (!abort.signal.aborted) { setData(value); setLoaded(true); setError(''); setSymbolId(value.symbols.find((s) => s.page === page)?.id ?? '') }
    }).catch((err: unknown) => { if (!abort.signal.aborted) setError(err instanceof Error ? err.message : 'Labels could not be loaded.') })
    return () => abort.abort()
  }, [open, loaded, docId, page])
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
  const symbol = symbols.find((s) => s.id === symbolId)
  return { open, mode, data, selection, error, busy, loaded, symbols, symbol, index, setIndex, page,
    toggle(next: 'label' | 'pin') { setOpen(true); setSelection(null); setMode((old) => old === next ? null : next) },
    close() { setOpen(false); setMode(null); setSelection(null) },
    showNotes() { setOpen(true); setMode(null); setSelection(null) },
    select(value: Selection) { setSelection(value); setMode(null); setOpen(true) },
    cancel() { setSelection(null); setMode(null) },
    pick(id: string) { setSymbolId(id); setIndex(0); setSelection(null) },
    reload() { setLoaded(false); setError(''); setOpen(false); requestAnimationFrame(() => setOpen(true)) },
    teach(name: string, note: string) {
      if (!selection || !('box' in selection)) return
      const current = generation.current
      void mutate(async (signal) => {
        const saved = await markupRequest<TaughtSymbol>(docId, '/symbols', { method: 'POST', signal, body: JSON.stringify({ page, box: selection.box, name, note }) })
        if (generation.current !== current) return
        setData((d) => ({ ...d, symbols: [...d.symbols, saved] })); setSymbolId(saved.id); setIndex(0); setSelection(null)
      })
    },
    review(status: MatchStatus) {
      const match = symbol?.matches[index]
      if (!symbol || !match) return
      const current = generation.current
      void mutate(async (signal) => {
        const saved = await markupRequest<TaughtSymbol>(docId, `/symbols/${symbol.id}`, { method: 'PATCH', signal, body: JSON.stringify({ statuses: { [match.id]: status } }) })
        if (generation.current !== current) return
        setData((d) => ({ ...d, symbols: d.symbols.map((s) => s.id === saved.id ? saved : s) })); setIndex(Math.min(index + 1, saved.matches.length - 1))
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
type Markup = ReturnType<typeof useSymbolMarkup>
export function SymbolMarkupTools({ markup, disabled, onActivate }: { markup: Markup; disabled: boolean; onActivate: () => void }) {
  return <><Button variant="ghost" size="xs" aria-label="Label a symbol" aria-pressed={markup.mode === 'label'} disabled={disabled || markup.busy} onClick={() => { onActivate(); markup.toggle('label') }}><PenLine size={16} />Label</Button>
    <Button variant="ghost" size="icon-sm" aria-label="Place a note pin" aria-pressed={markup.mode === 'pin'} disabled={disabled || markup.busy} onClick={() => { onActivate(); markup.toggle('pin') }}><MapPin size={16} /></Button>
    {!markup.open && <Button variant="ghost" size="xs" onClick={() => { onActivate(); markup.showNotes() }}>Labels & notes</Button>}</>
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
    {markup.open && markup.symbol?.matches.map((m, index) => <g key={m.id} className={`symbol-match is-${m.status} ${index === markup.index ? 'is-active' : ''}`} role="button" tabIndex={0} aria-label={`Symbol box ${index + 1}, ${m.status}`} onPointerDown={(e) => { if (!markup.mode) e.stopPropagation() }} onClick={() => markup.setIndex(index)} onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); markup.setIndex(index) } }}>
      <rect x={m.bbox[0]} y={m.bbox[1]} width={m.bbox[2] - m.bbox[0]} height={m.bbox[3] - m.bbox[1]} vectorEffect="non-scaling-stroke" />
      <svg x={m.bbox[0]} y={m.bbox[1]} width={Math.max(16, String(index + 1).length * 8) / scale} height={16 / scale} viewBox={`0 0 ${Math.max(16, String(index + 1).length * 8)} 16`}><rect width="100%" height="16" rx="3" /><text x="50%" y="12" textAnchor="middle">{index + 1}</text></svg>
    </g>)}
    {markup.data.pins.filter((p) => p.page === markup.page).map((pin) => <g key={pin.id} className="markup-note-pin" role="button" tabIndex={0} aria-label={`Pin ${pin.n}: ${pin.note}`} onPointerDown={(e) => { if (!markup.mode) e.stopPropagation() }} onClick={markup.showNotes} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); markup.showNotes() } }} transform={`translate(${pin.x},${pin.y}) scale(${1 / scale})`}><title>{pin.note}</title><circle r="10" /><text y="4" textAnchor="middle">{pin.n}</text></g>)}
    {box && <rect className="symbol-selection" x={box[0]} y={box[1]} width={box[2] - box[0]} height={box[3] - box[1]} vectorEffect="non-scaling-stroke" />}
    {markup.selection && 'point' in markup.selection && <circle className="symbol-selection" cx={markup.selection.point.x} cy={markup.selection.point.y} r={8 / scale} vectorEffect="non-scaling-stroke" />}
  </svg>
}

export function SymbolMarkupPanel({ markup, page, onFocus }: { markup: Markup; page: number; onFocus: (box: Bbox) => void }) {
  const [name, setName] = useState(''), [note, setNote] = useState('')
  const listId = useId()
  const panel = useRef<HTMLElement>(null)
  useEffect(() => { setName(''); setNote('') }, [markup.selection])
  const match = markup.symbol?.matches[markup.index]
  useEffect(() => { if (match) { onFocus(match.bbox); panel.current?.focus() } }, [match?.id, markup.symbol?.id]) // Focus a candidate without moving it when its status changes.
  return <section ref={panel} className="symbol-markup-panel" tabIndex={-1} aria-label="Labels and notes" onKeyDown={(event) => {
    if ((event.target as HTMLElement).closest('input,textarea,select') || markup.busy || !match) return
    if (['y', 'n', 'ArrowRight', 'ArrowDown', 'ArrowLeft', 'ArrowUp'].includes(event.key)) { event.preventDefault(); event.stopPropagation() }
    if (event.key.toLowerCase() === 'y') markup.review('confirmed')
    if (event.key.toLowerCase() === 'n') markup.review('rejected')
    if (['ArrowRight', 'ArrowDown'].includes(event.key)) markup.setIndex(Math.min(markup.index + 1, markup.symbol!.matches.length - 1))
    if (['ArrowLeft', 'ArrowUp'].includes(event.key)) markup.setIndex(Math.max(0, markup.index - 1))
  }}>
    <header><strong>Labels & notes</strong><Button variant="ghost" size="icon-xs" aria-label="Close labels and notes" onClick={markup.close}><X size={16} /></Button></header>
    {markup.error && <p role="alert">{markup.error} {!markup.loaded && <button onClick={markup.reload}>Retry</button>}</p>}
    {!markup.loaded && !markup.error && <p role="status">Loading saved labels…</p>}
    {markup.busy && <p role="status">{markup.selection && 'box' in markup.selection ? 'Finding similar symbols…' : 'Saving…'}</p>}
    {markup.mode && <p role="status">{markup.mode === 'label' ? 'Drag a tight box around one symbol. Zoom in for dense sheets.' : 'Click the drawing to place a numbered note.'}</p>}
    {markup.selection && <form onSubmit={(event) => { event.preventDefault(); if ('box' in markup.selection!) markup.teach(name.trim(), note.trim()); else markup.pin(note.trim()) }}>
      {'box' in markup.selection && <label>Symbol name<input autoFocus list={listId} value={name} maxLength={160} required onChange={(e) => setName(e.target.value)} placeholder="e.g. Supply air terminal" /><datalist id={listId}>{markup.data.suggestions.map((s) => <option key={s} value={s} />)}</datalist></label>}
      <label>{'box' in markup.selection ? 'Note (optional)' : 'Pin note'}<textarea autoFocus={'point' in markup.selection} required={'point' in markup.selection} value={note} maxLength={4000} onChange={(e) => setNote(e.target.value)} /></label>
      <Button type="submit" variant="primary" size="sm" disabled={markup.busy || !markup.loaded || ('box' in markup.selection ? !name.trim() : !note.trim())}>{'box' in markup.selection ? 'Find all like this' : 'Save pin'}</Button><Button size="sm" variant="ghost" disabled={markup.busy} onClick={markup.cancel}>Cancel</Button>
    </form>}
    {markup.symbols.length > 0 && <label>Saved symbol<select value={markup.symbol?.id ?? ''} onChange={(e) => markup.pick(e.target.value)}><option value="" disabled>Choose a label</option>{markup.symbols.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>}
    {markup.symbol && <>
      <p className="markup-count"><strong>{markup.symbol.summary.found} boxes</strong> · {markup.symbol.summary.confirmed} confirmed · {markup.symbol.summary.pending} pending · {markup.symbol.summary.rejected} rejected</p>
      <p>{markup.symbol.note}</p><p className="markup-caution">Auto-matches can include legend marks, text and other false hits, and miss symbols. Confirm or reject each box; this is not an exhaustive drawing count.</p>
      {markup.symbol.matcher_note && <p>{markup.symbol.matcher_note}</p>}
      <ul className="markup-room-counts">{Object.entries(markup.symbol.summary.rooms).map(([room, count]) => <li key={room}>{room}: {count}</li>)}</ul>
      {match && <><p>Box {markup.index + 1} of {markup.symbol.matches.length} · {match.status}</p><div className="markup-review-actions"><Button size="sm" disabled={markup.busy} onClick={() => markup.review('confirmed')}>Confirm (Y)</Button><Button size="sm" disabled={markup.busy} onClick={() => markup.review('rejected')}>Reject (N)</Button><Button size="sm" disabled={markup.busy} onClick={() => markup.review('pending')}>Reset</Button></div><small>Arrow keys move between boxes.</small></>}
      <div className="markup-box-list">{markup.symbol.matches.map((m, i) => <button key={m.id} type="button" aria-pressed={i === markup.index} onClick={() => { markup.setIndex(i); onFocus(m.bbox); panel.current?.focus() }}>Box {i + 1}<span>{m.status}</span></button>)}</div>
    </>}
    <h3>Note pins · Page {page}</h3><p>Saved notes are included in Export report.</p>
    <ol className="markup-pin-list">{markup.data.pins.filter((p) => p.page === page).map((pin) => <li key={pin.id}><button onClick={() => onFocus([pin.x - 30, pin.y - 30, pin.x + 30, pin.y + 30])}>Pin {pin.n}: {pin.note}</button><Button variant="ghost" size="xs" disabled={markup.busy} onClick={() => markup.removePin(pin.id)}>Delete</Button></li>)}</ol>
  </section>
}
