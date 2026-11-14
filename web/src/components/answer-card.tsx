import { useEffect, useState } from 'react'
import { FileText, Layers3, Box, Smartphone } from 'lucide-react'
import { AdvisorCardView } from '../viewer3d/AdvisorCardView'
import { onAdvisorCards } from '../viewer3d/liveHighlight'
import type { AdvisorCard } from '../viewer3d/advisor'
import { Tooltip } from './ui'
import { CITATION_CAP, humanizeIds, isOneLine, parseBlocks, plainQuote } from '../lib/answer-text'
import type { Answer, Citation, Document } from '../lib/types'
import { SpeakButton } from './voice-controls'
import { ExportAnswerButton } from './answer-export'
import { answerTableSelection } from '../lib/ar-bridge'
import { ShowOnTableButton } from './show-on-table'
import { SceneCommandTags } from './scene-command-tags'
import { sceneOpen } from '../lib/scene-open'
import { isPaired, onPairingChange } from '../lib/pairing'
import { PairPhoneButton } from './pair-phone'
import type { DrawingEdits } from '../lib/scene-edits'

export function formatCost(total: number): string {
  return total > 0 && total < 0.0001 ? '< $0.0001' : `$${total.toFixed(4)}`
}

function CitationChip({ citation, selected, onOpenCitation }: { citation: Citation; selected?: Citation; onOpenCitation: (citation: Citation) => void }) {
  return <button type="button" className="citation-chip" aria-label={`Open citation ${citation.n}`} aria-pressed={selected?.n === citation.n} onClick={() => onOpenCitation(citation)}>{citation.n}</button>
}

function labelsOf(answer: Answer): Record<string, string> {
  return Object.fromEntries(answer.evidence.boxes.map((box) => [box.item_id, box.label]))
}

function InlineText({ text, answer, selected, onOpenCitation }: { text: string; answer: Answer; selected?: Citation; onOpenCitation: (citation: Citation) => void }) {
  return <>{text.split(/(\*\*[\s\S]+?\*\*|\[\d+\])/g).map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) return <strong key={index}>{part.slice(2, -2)}</strong>
    const number = part.match(/^\[(\d+)\]$/)?.[1]
    const citation = number ? answer.citations.find((item) => item.n === Number(number)) : undefined
    return citation ? <CitationChip key={index} citation={citation} selected={selected} onOpenCitation={onOpenCitation} /> : part
  })}</>
}

function AnswerBody({ answer, selected, onOpenCitation }: { answer: Answer; selected?: Citation; onOpenCitation: (citation: Citation) => void }) {
  const labels = labelsOf(answer)
  if (answer.answer.abstained) return <p className="answer-text">{humanizeIds(answer.answer.text_md, labels).replace(/\*\*/g, '').replace(/\s*\[\d+\]/g, '')}</p>
  const blocks = parseBlocks(humanizeIds(answer.answer.text_md, labels))
  const inline = (text: string) => <InlineText text={text} answer={answer} selected={selected} onOpenCitation={onOpenCitation} />
  if (!blocks.some((block) => block.type === 'table')) return <p className="answer-text">{inline(humanizeIds(answer.answer.text_md, labels))}</p>
  return <div className="answer-text answer-rich">{blocks.map((block, index) => block.type === 'table'
    ? <div className="answer-table-wrap" key={index}><table className="answer-table"><thead><tr>{block.header.map((cell, c) => <th key={c} scope="col">{inline(cell)}</th>)}</tr></thead>
      <tbody>{block.rows.map((row, r) => <tr key={r}>{row.map((cell, c) => <td key={c}>{inline(cell)}</td>)}</tr>)}</tbody></table></div>
    : block.text.trim() ? <p key={index}>{inline(block.text.trim())}</p> : null)}</div>
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

/** Inline hint for "show on table" answers: AR runs in the iOS app, not the browser. */
export function ArHint() {
  const [paired, setPaired] = useState(isPaired())
  useEffect(() => onPairingChange(() => setPaired(isPaired())), [])
  return <div className="ar-hint" role="note" data-testid="ar-hint">
    <Smartphone size={16} aria-hidden="true" />
    <p>Open the Stoa Pro app on your iPhone and tap <strong>Show on table</strong>.</p>
    {!paired && <PairPhoneButton />}
  </div>
}

export function AnswerCard({ answer, docs, demo, activeCitation, onOpenCitation, onVisualise, edits, busy, onUndo, onOpenItem, chatId }: {
  answer: Answer; docs: Document[]; demo: boolean; activeCitation?: Citation; onOpenCitation: (citation: Citation) => void
  /** Open the viewer straight in 3D. */
  onVisualise?: (citation: Citation) => void
  edits?: DrawingEdits; busy?: boolean; onUndo?: () => void; onOpenItem?: (id: string) => void
  chatId?: string | null
}) {
  const allCitations = answer.answer.abstained ? [] : answer.citations
  const [showAll, setShowAll] = useState(false)
  const hidden = showAll ? 0 : Math.max(0, allCitations.length - CITATION_CAP)
  const citations = hidden ? allCitations.slice(0, CITATION_CAP) : allCitations
  const labels = labelsOf(answer)
  const oneLine = isOneLine(answer.answer.text_md)
  const docChips = answer.doc_ids.map((docId) => ({ docId, title: docs.find((doc) => doc.doc_id === docId)?.title ?? docId, first: allCitations.find((citation) => citation.doc_id === docId) }))
  const advice = useAnswerAdvice(answer, chatId)
  const table = answerTableSelection(answer)
  const generated = demo || answer.trace.some((step) => step.stub)
  const callDetails = answer.cost.calls.length ? JSON.stringify(answer.cost.calls, null, 2) : 'No model calls.'
  const sources = [...new Set(citations.map((citation) => citation.doc_id))].map((docId) => ({
    docId, title: docs.find((doc) => doc.doc_id === docId)?.title ?? docId,
    citations: citations.filter((citation) => citation.doc_id === docId),
  }))
  const cost = <Tooltip content={callDetails}><span className="cost-chip" data-testid="answer-cost" tabIndex={0} aria-label={`Answer cost ${formatCost(answer.cost.usd_total)}`} title={callDetails}>{formatCost(answer.cost.usd_total)}</span></Tooltip>
  return <article className="exchange" data-testid="answer-card">
    <div className="question-bubble">{answer.question}</div>
    <details className="answer-detail thought-process"><summary>Show thought process</summary>{answer.trace.map((trace, index) => <p key={index}>{trace.detail}</p>)}</details>
    <AnswerBody answer={answer} selected={activeCitation} onOpenCitation={onOpenCitation} />
    {!!docChips.length && <div className="answer-docs" aria-label="Documents used" data-testid="answer-docs">{docChips.map(({ docId, title, first }) => first
      ? <button type="button" key={docId} className="source-file-chip answer-doc-chip" aria-label={`Open document ${title}`} onClick={() => onOpenCitation(first)}><FileText size={14} /><span>{title}</span></button>
      : <span key={docId} className="source-file-chip answer-doc-chip"><FileText size={14} /><span>{title}</span></span>)}</div>}
    {sceneOpen(answer) === 'ar' && <ArHint />}
    <SceneCommandTags answer={answer} edits={edits} busy={busy} onUndo={onUndo} onOpenItem={onOpenItem} />
    {!!advice.length && <div className="advisor-card-list" aria-label="Advice for this change" data-testid="answer-advisor-cards">
      {advice.map((card) => <AdvisorCardView key={card.card_id} card={card} />)}
    </div>}
    {!!citations.length && <>
      {!oneLine && <h3 className="source-heading">Where it is set out</h3>}
      <ol className="source-list">{sources.map((source) => <li key={source.docId}>
        <div className="source-document"><strong>{source.title.replace(/\.[a-z0-9]+(?:\s*[—–-]?\s*generated for demo)?$/i, '')}</strong> (<button type="button" className="source-file-chip" aria-label={`Open source document ${source.title}`} onClick={() => onOpenCitation(source.citations[0])}><FileText size={14} /><span>{source.title}</span></button>)</div>
        <ul>{source.citations.map((citation) => <li key={citation.n}>{(citation.quote && humanizeIds(plainQuote(citation.quote), labels)) || `Page ${citation.page}${citation.item_ids.length ? ` · ${citation.item_ids.length} cited ${citation.item_ids.length === 1 ? 'item' : 'items'}` : ''}`} <CitationChip citation={citation} selected={activeCitation} onOpenCitation={onOpenCitation} /></li>)}</ul>
      </li>)}</ol>
      {(hidden > 0 || showAll) && allCitations.length > CITATION_CAP && <button type="button" className="citation-more" aria-expanded={showAll} onClick={() => setShowAll((value) => !value)}>{showAll ? 'Show fewer' : `+${hidden} more`}</button>}
    </>}
    <div className="answer-actions">
      {!!citations.length && <details className="answer-detail sources-detail"><summary className="sources-summary" aria-label={`Sources ${allCitations.length}`}><FileText size={14} /><span>Sources</span><span className="source-count">{allCitations.length}</span></summary>{allCitations.map((citation) => <p key={citation.n}>
        <CitationChip citation={citation} selected={activeCitation} onOpenCitation={onOpenCitation} /> {humanizeIds(citation.item_ids.join(', '), labels)} · Page {citation.page}
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
