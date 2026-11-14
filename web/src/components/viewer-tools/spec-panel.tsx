import { X } from 'lucide-react'
import type { Citation } from '../../lib/types'
import type { SheetText } from './sheet-text'
import { Button } from '../ui'

export function SpecPanel({ citation, title, text, onClose }: { citation: Citation; title: string; text: SheetText[]; onClose: () => void }) {
  const passage = citation.quote?.trim()
  const context = text.map((entry) => entry.text).join(' ')
  const start = passage ? context.toLocaleLowerCase().indexOf(passage.toLocaleLowerCase()) : -1
  return <aside className="viewer-spec-panel" aria-label="Cited passage">
    <header><div><strong>Specification / notes</strong><small>{title} · Page {citation.page} · [{citation.n}]</small></div><Button variant="ghost" size="icon" aria-label="Close cited passage" onClick={onClose}><X size={16} /></Button></header>
    <div className="viewer-spec-content">
      {passage ? <p>{start >= 0 && context.slice(Math.max(0, start - 220), start)}<mark data-testid="cited-passage">{passage}</mark>{start >= 0 && context.slice(start + passage.length, start + passage.length + 220)}</p>
        : <p>The source did not supply a quoted passage. See the highlighted source on the sheet.</p>}
    </div>
  </aside>
}
