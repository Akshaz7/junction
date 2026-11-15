import { useState } from 'react'
import { ChevronRight } from 'lucide-react'
import type { TraceStep } from '../lib/types'
import { ThinkingText } from './thinking-text'
import './thinking-row.css'

function ThinkingMark() {
  const [missing, setMissing] = useState(false)
  return <span className="thinking-mark" aria-hidden="true"><span className="thinking-glyph">
    {missing
      ? <svg viewBox="0 0 24 24" fill="currentColor"><path d="M1 10 9 2h14l-6 6H10l-4 4H1Zm22 4-8 8H1l6-6h7l4-4h5Z" /></svg>
      : <img src="/brand/stoa-logo.svg" alt="" onError={() => setMissing(true)} />}
  </span></span>
}

export function thinkingLabel(text: string) {
  const clean = text.trim() || 'Thinking…'
  if (clean.includes(':')) return clean
  return clean.replace(/^(\S+)\s+/, '$1: ')
}

/** One live status row; the step history stays behind the same disclosure. */
export function ThinkingRow({ statuses = [], traces = [], active = false }: {
  statuses?: string[]; traces?: TraceStep[]; active?: boolean
}) {
  const text = thinkingLabel(statuses.at(-1) || 'Thinking…')
  const steps = [...new Set([...statuses, ...traces.map((trace) => trace.detail)])]
  return <details className={`answer-detail thought-process thinking-row${active ? ' is-active' : ''}`}>
    <summary>
      <ThinkingMark />
      {active
        ? <span className="status-lines" role="status" aria-live="polite"><ThinkingText text={text} /></span>
        : <span>Show thought process</span>}
      <ChevronRight className="thinking-chevron" size={14} aria-hidden="true" />
    </summary>
    {!!steps.length && <ul className="status-trail" aria-label="Steps so far">{steps.map((step, index) => <li key={index}>{step}</li>)}</ul>}
  </details>
}
