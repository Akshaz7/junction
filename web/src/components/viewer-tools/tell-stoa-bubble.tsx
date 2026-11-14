import { useEffect, useId, useRef, useState } from 'react'
import type { CSSProperties, KeyboardEvent } from 'react'
import { TAUGHT_KINDS, kindFor } from './taught-kinds'

export type Box = [number, number, number, number]

const WIDTH = 320
const GAP = 10
const MARGIN = 8
const HEIGHT = 150 // composer, chips and the label pill: decides whether it fits below the box

/** Where the bubble sits, in stage pixels: under the box, flipped above when the stage edge is too close, clamped inside. */
export function bubbleSpot(box: Box, view: { x: number; y: number; scale: number }, stage: { width: number; height: number }) {
  const width = Math.min(WIDTH, Math.max(160, stage.width - MARGIN * 2))
  const left = view.x + box[0] * view.scale
  const top = view.y + box[1] * view.scale, bottom = view.y + box[3] * view.scale
  const below = bottom + GAP, above = top - GAP - HEIGHT
  const y = below + HEIGHT <= stage.height - MARGIN || above < MARGIN ? Math.min(below, stage.height - HEIGHT - MARGIN) : above
  const x = Math.max(MARGIN, Math.min(left, stage.width - width - MARGIN))
  return { x, y: Math.max(MARGIN, y), width }
}

export function TellStoaBubble({ box, view, stage, busy, error, legend, initial, onSave, onDelete, onClose }: {
  box: Box
  view: { x: number; y: number; scale: number }
  stage: { width: number; height: number }
  busy: boolean
  error?: string
  /** Words from the sheet's own legend, offered as extra chips. */
  legend?: string[]
  /** Set when editing a saved mark: the field starts with its name. */
  initial?: { name: string; kind: string | null }
  onSave: (name: string, kind: string | null) => void
  onDelete?: () => void
  onClose: () => void
}) {
  const [text, setText] = useState(initial?.name ?? '')
  const [chosen, setChosen] = useState<string | null>(initial?.kind ?? null)
  const input = useRef<HTMLInputElement>(null)
  const hint = useId(), tip = useId()
  const spot = bubbleSpot(box, view, stage)
  const mapped = chosen ? TAUGHT_KINDS.find((kind) => kind.id === chosen) ?? null : kindFor(text)
  const extra = (legend ?? []).filter((word) => !TAUGHT_KINDS.some((kind) => kind.label.toLowerCase() === word.toLowerCase())).slice(0, 4)
  useEffect(() => { input.current?.focus({ preventScroll: true }); input.current?.select() }, [])
  function send() {
    const value = text.trim()
    if (!value || busy) return
    onSave(value, mapped?.id ?? null)
  }
  function keys(event: KeyboardEvent) {
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); onClose() }
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing && (event.target as HTMLElement).tagName === 'INPUT') { event.preventDefault(); send() }
  }
  return <div className="tell-stoa" role="group" aria-label={initial ? 'Edit this mark' : 'Tell Stoa what this is'} data-testid="tell-stoa"
    style={{ '--bubble-x': `${spot.x}px`, '--bubble-y': `${spot.y}px`, '--bubble-w': `${spot.width}px` } as CSSProperties}
    onPointerDown={(event) => event.stopPropagation()} onWheel={(event) => event.stopPropagation()} onKeyDown={keys}>
    <div className="tell-stoa-composer">
      <input ref={input} type="text" value={text} maxLength={160} placeholder="Mark this as… (e.g. door)" autoComplete="off"
        aria-label="What the highlighted item is" aria-describedby={hint} disabled={busy} onChange={(event) => { setText(event.target.value); setChosen(null) }} />
      <button type="button" className="tell-stoa-send" aria-label={initial ? 'Save changes' : 'Save mark'} disabled={!text.trim() || busy} onClick={send}>
        <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path d="M8 13V3M3.5 7.5 8 3l4.5 4.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </button>
    </div>
    <div className="tell-stoa-chips" role="group" aria-label="Common items">
      {TAUGHT_KINDS.map((kind) => <button key={kind.id} type="button" className="tell-stoa-chip" aria-pressed={mapped?.id === kind.id && (chosen === kind.id || kindFor(text)?.id === kind.id)} disabled={busy}
        onClick={() => { setText(kind.label); setChosen(kind.id); input.current?.focus() }}>{kind.label}</button>)}
      {extra.map((word) => <button key={word} type="button" className="tell-stoa-chip is-legend" disabled={busy} onClick={() => { setText(word); setChosen(null); input.current?.focus() }}>{word}</button>)}
    </div>
    <p id={hint} className="tell-stoa-status" role={error ? 'alert' : 'status'}>
      {error || (busy ? 'Saving…' : mapped ? `Counts as: ${mapped.label}` : text.trim() ? `Saved as your own item: ${text.trim()}` : '')}
    </p>
    <div className="tell-stoa-foot">
      <span className="tell-stoa-pill" tabIndex={0} aria-describedby={tip}>
        <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true"><path d="M3 4h10M4.5 4v8M8 4v8M11.5 4v8M3 12.5h10" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" /></svg>
        Tell Stoa
        <span id={tip} role="tooltip" className="tell-stoa-tip">Tell Stoa what this is. Stoa saves it and counts it as that item in every answer, the 3D model and reports.</span>
      </span>
      {onDelete && <button type="button" className="tell-stoa-delete" disabled={busy} onClick={onDelete}>Delete mark</button>}
    </div>
  </div>
}
