import { FileText, Layers3 } from 'lucide-react'
import { Tooltip } from './ui'
import type { Answer, Citation, Document } from '../lib/types'

export function formatCost(total: number): string {
  return total > 0 && total < 0.0001 ? '< $0.0001' : `$${total.toFixed(4)}`
}

function CitationChip({ citation, onOpenCitation }: { citation: Citation; onOpenCitation: (citation: Citation) => void }) {
  return <button type="button" className="citation-chip" aria-label={`Open citation ${citation.n}`} onClick={() => onOpenCitation(citation)}>[{citation.n}]</button>
}

function AnswerText({ answer, onOpenCitation }: { answer: Answer; onOpenCitation: (citation: Citation) => void }) {
  if (answer.answer.abstained) return answer.answer.text_md.replace(/\*\*/g, '').replace(/\s*\[\d+\]/g, '')
  return answer.answer.text_md.split(/(\*\*[\s\S]+?\*\*|\[\d+\])/g).map((part, index) => {
    if (part.startsWith('**')) return <strong key={index}>{part.slice(2, -2)}</strong>
    const number = part.match(/^\[(\d+)\]$/)?.[1]
    const citation = number ? answer.citations.find((item) => item.n === Number(number)) : undefined
    return citation ? <CitationChip key={index} citation={citation} onOpenCitation={onOpenCitation} /> : part
  })
}

export function AnswerCard({ answer, docs, demo, onOpenCitation }: {
  answer: Answer; docs: Document[]; demo: boolean; onOpenCitation: (citation: Citation) => void
}) {
  const citations = answer.answer.abstained ? [] : answer.citations
  const generated = demo || answer.trace.some((step) => step.stub)
  const callDetails = answer.cost.calls.length ? JSON.stringify(answer.cost.calls, null, 2) : 'No model calls.'
  return <article className="exchange">
    <div className="question-bubble">{answer.question}</div>
    <div className="answer-brand"><Layers3 size={17} /><strong>Hologram</strong>{generated && <span>Answer generated for demo</span>}</div>
    <p className="answer-text"><AnswerText answer={answer} onOpenCitation={onOpenCitation} /></p>
    {!!citations.length && <>
      <h3 className="source-heading">Where it is set out</h3>
      <ol className="source-list">{citations.map((citation) => <li key={citation.n}>
        <CitationChip citation={citation} onOpenCitation={onOpenCitation} /><FileText size={15} />
        <span>{docs.find((doc) => doc.doc_id === citation.doc_id)?.title ?? citation.doc_id}<small>Page {citation.page}</small>{citation.quote && <span className="source-quote">{citation.quote}</span>}</span>
      </li>)}</ol>
      <details className="answer-detail"><summary>Sources ({citations.length})</summary>{citations.map((citation) => <p key={citation.n}>
        <CitationChip citation={citation} onOpenCitation={onOpenCitation} /> {citation.item_ids.join(', ')} · Page {citation.page}
      </p>)}</details>
    </>}
    <div className="answer-footer">
      <details className="answer-detail"><summary>Show thought process</summary>{answer.trace.map((trace, index) => <p key={index}>{trace.detail}</p>)}</details>
      <Tooltip content={callDetails}><span className="chip cost-chip" data-testid="answer-cost" tabIndex={0} aria-label={`Answer cost ${formatCost(answer.cost.usd_total)}`} title={callDetails}>{formatCost(answer.cost.usd_total)}</span></Tooltip>
    </div>
  </article>
}
