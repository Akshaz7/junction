import { useEffect, useRef } from 'react'
import { ClipboardList, Download, MoreHorizontal } from 'lucide-react'
import type { Answer, Document } from '../lib/types'
import { answerTableSelection } from '../lib/ar-bridge'
import { downloadTakeoffCsv, parseTakeoff, TAKEOFF_QUESTION } from '../lib/takeoff'
import { ExportAnswerButton } from './answer-export'
import { ShowOnTableButton } from './show-on-table'
import { SpeakButton } from './voice-controls'
import './answer-more-actions.css'

/** Secondary actions live beside the thought process; the footer stays Sources + Visualise it. */
export function AnswerMoreActions({ answer, docs, chatId, demo, onAsk }: {
  answer: Answer; docs: Document[]; chatId?: string | null; demo: boolean; onAsk?: (question: string) => void
}) {
  const details = useRef<HTMLDetailsElement>(null)
  const takeoff = parseTakeoff(answer, docs)
  const table = answerTableSelection(answer)
  useEffect(() => {
    function dismiss(event: PointerEvent) {
      if (event.target instanceof Node && !details.current?.contains(event.target) && !document.querySelector('dialog[open]')) {
        details.current?.removeAttribute('open')
      }
    }
    document.addEventListener('pointerdown', dismiss)
    return () => document.removeEventListener('pointerdown', dismiss)
  }, [])
  return <details ref={details} className="answer-more" onKeyDown={(event) => {
    // Dialog portals bubble through React; let their own Escape handling close them first.
    if (event.target instanceof Element && event.target.closest('dialog')) return
    if (event.key === 'Escape' && details.current?.open) {
      event.preventDefault(); event.stopPropagation()
      details.current.open = false
      details.current.querySelector('summary')?.focus()
    }
  }}>
    <summary aria-label="More answer actions"><MoreHorizontal size={16} aria-hidden="true" /></summary>
    <div className="answer-more-popover" role="group" aria-label="Answer actions">
      <SpeakButton text={answer.answer.text_md} label="Read aloud" />
      <ExportAnswerButton answer={answer} docs={docs} chatId={chatId} demo={demo} />
      {takeoff && <button type="button" className="show-on-table takeoff-csv" data-testid="takeoff-csv" onClick={() => downloadTakeoffCsv(takeoff)}><Download size={15} aria-hidden="true" /><span>Download CSV</span></button>}
      {!takeoff && onAsk && !answer.answer.abstained && <button type="button" className="show-on-table takeoff-sheet" data-testid="takeoff-sheet" onClick={() => onAsk(TAKEOFF_QUESTION)}><ClipboardList size={15} aria-hidden="true" /><span>Take-off sheet</span></button>}
      {table && <ShowOnTableButton docId={table.doc_id} itemIds={table.item_ids} chatId={chatId} />}
    </div>
  </details>
}
