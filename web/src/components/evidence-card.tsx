import type { Answer, Citation } from '../lib/types'
import { qualitySummary } from '../lib/scene-quality'
import './evidence-card.css'

/** "How we know": the steps behind an answer and how sure we are. Steps with a citation open it. */
export function EvidenceCard({ answer, selected, onOpenCitation }: { answer: Answer; selected?: Citation; onOpenCitation: (citation: Citation) => void }) {
  const reasoning = answer.reasoning
  if (!reasoning?.steps?.length) return null
  const { confidence } = reasoning
  const quality = qualitySummary(reasoning.quality)
  const tone = confidence.label === 'Estimate' ? 'is-estimate' : 'is-verified'
  return <section className="evidence-card" aria-label="How we know" data-testid="evidence-card">
    <h3 className="evidence-heading">How we know</h3>
    <ol className="evidence-steps">
      {reasoning.steps.map((step, index) => {
        const citation = step.cite == null ? undefined : answer.citations.find((item) => item.n === step.cite)
        const body = <>
          <span className="evidence-dot" aria-hidden="true">{index + 1}</span>
          <span className="evidence-text"><strong>{step.title}</strong> {step.text}
            {step.ok === true && <span className="evidence-ok">matches</span>}
            {step.ok === false && <span className="evidence-differs">differs</span>}
            {citation && <span className={`citation-chip${selected?.n === citation.n ? ' is-selected' : ''}`} aria-hidden="true">{citation.n}</span>}
          </span>
        </>
        return <li key={index} className="evidence-step" data-kind={step.kind}>
          {citation
            ? <button type="button" className="evidence-row is-clickable" aria-label={`${step.title}: ${step.text}. Open citation ${citation.n}`} onClick={() => onOpenCitation(citation)}>{body}</button>
            : <div className="evidence-row">{body}</div>}
        </li>
      })}
    </ol>
    <div className="evidence-confidence">
      <span className={`evidence-pill ${tone}`} aria-label={`Confidence: ${confidence.label}, ${confidence.pct} percent`}>{confidence.label} · {confidence.pct}%</span>
      <span className="evidence-reason">{confidence.reason}</span>
    </div>
    {quality && <p className="evidence-quality" data-testid="evidence-quality">3D accuracy: {quality}</p>}
    {confidence.improve && <p className="evidence-improve">To make it exact: {confidence.improve}</p>}
  </section>
}
