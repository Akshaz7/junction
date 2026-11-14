import { useEffect, useState } from 'react'
import { FileText, Layers3, Box } from 'lucide-react'
import { AdvisorCardView } from '../viewer3d/AdvisorCardView'
import { onAdvisorCards } from '../viewer3d/liveHighlight'
import type { AdvisorCard } from '../viewer3d/advisor'
import { Tooltip } from './ui'
import type { Answer, Citation, Document } from '../lib/types'
import { SpeakButton } from './voice-controls'
import { ExportAnswerButton } from './answer-export'
import { answerTableSelection } from '../lib/ar-bridge'
import { ShowOnTableButton } from './show-on-table'
import { SceneCommandTags } from './scene-command-tags'
import type { DrawingEdits } from '../lib/scene-edits'

export function formatCost(total: number): string {
  return total > 0 && total < 0.0001 ? '< $0.0001' : `$${total.toFixed(4)}`
}

function CitationChip({ citation, selected, onOpenCitation }: { citation: Citation; selected?: Citation; onOpenCitation: (citation: Citation) => void }) {
  return <button type="button" className="citation-chip" aria-label={`Open citation ${citation.n}`} aria-pressed={selected?.n === citation.n} onClick={() => onOpenCitation(citation)}>{citation.n}</button>
}

function AnswerText({ answer, selected, onOpenCitation }: { answer: Answer; selected?: Citation; onOpenCitation: (citation: Citation) => void }) {
  if (answer.answer.abstained) return answer.answer.text_md.replace(/\*\*/g, '').replace(/\s*\[\d+\]/g, '')
  return answer.answer.text_md.split(/(\*\*[\s\S]+?\*\*|\[\d+\])/g).map((part, index) => {
    if (part.startsWith('**')) return <strong key={index}>{part.slice(2, -2)}</strong>
    const number = part.match(/^\[(\d+)\]$/)?.[1]
    const citation = number ? answer.citations.find((item) => item.n === Number(number)) : undefined
    return citation ? <CitationChip key={index} citation={citation} selected={selected} onOpenCitation={onOpenCitation} /> : part
  })
}

/** Edit checks for this answer: the cards saved on it, replaced by live `advisor.cards` for this chat when it hid something. */
function useAnswerAdvice(answer: Answer, chatId?: string | null): AdvisorCard[] {
  const [cards, setCards] = useState<AdvisorCard[]>(answer.advisor_cards ?? [])
  const docId = answer.evidence.scene.doc_id || answer.doc_ids[0]
  const hides = !!answer.evidence.scene.commands?.some((command) => command.op === 'hide')
  useEffect(() => { setCards(answer.advisor_cards ?? []) }, [answer.advisor_cards, answer.answer_id])
  useEffect(() => {
    if (!hides || !chatId) return
    return onAdvisorCards((event) => { if (event.doc_id === docId && event.chat_id === chatId) setCards(event.cards) })
  }, [hides, chatId, docId])
  return cards
}

export function AnswerCard({ answer, docs, demo, activeCitation, onOpenCitation, onVisualise, edits, busy, onUndo, onOpenItem, chatId }: {
  answer: Answer; docs: Document[]; demo: boolean; activeCitation?: Citation; onOpenCitation: (citation: Citation) => void
  /** Open the viewer straight in 3D. */
  onVisualise?: (citation: Citation) => void
  edits?: DrawingEdits; busy?: boolean; onUndo?: () => void; onOpenItem?: (id: string) => void
  chatId?: string | null
}) {
  const citations = answer.answer.abstained ? [] : answer.citations
  const advice = useAnswerAdvice(answer, chatId)
  const table = answerTableSelection(answer)
  const generated = demo || answer.trace.some((step) => step.stub)
  const callDetails = answer.cost.calls.length ? JSON.stringify(answer.cost.calls, null, 2) : 'No model calls.'
  const sources = [...new Set(citations.map((citation) => citation.doc_id))].map((docId) => ({
    docId, title: docs.find((doc) => doc.doc_id === docId)?.title ?? docId,
    citations: citations.filter((citation) => citation.doc_id === docId),
  }))
  const cost = <Tooltip content={callDetails}><span className="cost-chip" data-testid="answer-cost" tabIndex={0} aria-label={`Answer cost ${formatCost(answer.cost.usd_total)}`} title={callDetails}>{formatCost(answer.cost.usd_total)}</span></Tooltip>
  return <article className="exchange">
    <div className="question-bubble">{answer.question}</div>
    <details className="answer-detail thought-process"><summary>Show thought process</summary>{answer.trace.map((trace, index) => <p key={index}>{trace.detail}</p>)}</details>
    <p className="answer-text"><AnswerText answer={answer} selected={activeCitation} onOpenCitation={onOpenCitation} /></p>
    <SceneCommandTags answer={answer} edits={edits} busy={busy} onUndo={onUndo} onOpenItem={onOpenItem} />
    {!!advice.length && <div className="advisor-card-list" aria-label="Advice for this change" data-testid="answer-advisor-cards">
      {advice.map((card) => <AdvisorCardView key={card.card_id} card={card} />)}
    </div>}
    {!!citations.length && <>
      <h3 className="source-heading">Where it is set out</h3>
      <ol className="source-list">{sources.map((source) => <li key={source.docId}>
        <div className="source-document"><strong>{source.title.replace(/\.[a-z0-9]+(?:\s*[—–-]?\s*generated for demo)?$/i, '')}</strong> (<button type="button" className="source-file-chip" aria-label={`Open source document ${source.title}`} onClick={() => onOpenCitation(source.citations[0])}><FileText size={14} /><span>{source.title}</span></button>)</div>
        <ul>{source.citations.map((citation) => <li key={citation.n}>{citation.quote || `Page ${citation.page}${citation.item_ids.length ? ` · ${citation.item_ids.length} cited ${citation.item_ids.length === 1 ? 'item' : 'items'}` : ''}`} <CitationChip citation={citation} selected={activeCitation} onOpenCitation={onOpenCitation} /></li>)}</ul>
      </li>)}</ol>
    </>}
    <div className="answer-actions">
      {!!citations.length && <details className="answer-detail sources-detail"><summary className="sources-summary" aria-label={`Sources ${citations.length}`}><FileText size={14} /><span>Sources</span><span className="source-count">{citations.length}</span></summary>{citations.map((citation) => <p key={citation.n}>
        <CitationChip citation={citation} selected={activeCitation} onOpenCitation={onOpenCitation} /> {citation.item_ids.join(', ')} · Page {citation.page}
      </p>)}</details>}
      <SpeakButton text={answer.answer.text_md} />
      <ExportAnswerButton answer={answer} docs={docs} chatId={chatId} demo={demo} />
      {!!citations.length && <button type="button" className="show-on-table visualise-from-answer" onClick={() => (onVisualise ?? onOpenCitation)(citations[0])}><Box size={15} aria-hidden="true" /><span>Visualise it</span></button>}
      {table && <ShowOnTableButton docId={table.doc_id} itemIds={table.item_ids} chatId={chatId} />}
      {cost}
    </div>
    <div className="answer-footer">
      {generated && <div className="answer-brand"><Layers3 size={14} /><span>Answer generated for demo</span></div>}
    </div>
  </article>
}
