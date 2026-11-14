import type { Answer, Citation } from '../lib/types'
import { keyNumbers } from '../lib/calc-view'
import { confidenceText, marginText } from '../lib/evidence-format'
import './evidence-card.css'

/** "How we know": the steps behind an answer and how sure we are. Steps with a citation open it. */
export function EvidenceCard({ answer, selected, onOpenCitation, onShowCalculation }: { answer: Answer; selected?: Citation; onOpenCitation: (citation: Citation) => void; onShowCalculation?: () => void }) {
  const reasoning = answer.reasoning
  if (!reasoning) return null
  const { confidence } = reasoning
  const numbers = keyNumbers(reasoning.calc)
  const tone = confidence.label === 'Estimate' ? 'is-estimate' : 'is-verified'
  return <section className="evidence-card" aria-label="How we know" data-testid="evidence-card">
    <h3 className="evidence-heading">How we know</h3>
    {!!numbers.length && <dl className="evidence-numbers" data-testid="evidence-numbers">{numbers.map((n) => <div key={n.label}><dt>{n.label}</dt><dd>{n.text}</dd></div>)}</dl>}
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
    {reasoning.based_on && <p className="evidence-quantity">{reasoning.based_on.text}</p>}
    {reasoning.margin && <div className="evidence-quantity">
      <p>{marginText(reasoning.margin)}</p>
      {Object.entries(reasoning.margin.by_kind ?? {}).map(([kind, margin]) => <p key={kind}>{kind}: {marginText(margin)}{margin.sources.length > 0 && <span className="evidence-reason"> Sources: {margin.sources.join('; ')}</span>}</p>)}
      {reasoning.margin.sources.length > 0 && <p className="evidence-reason">Sources: {reasoning.margin.sources.join('; ')}</p>}
    </div>}
    <div className="evidence-confidence">
      <span className={`evidence-pill ${tone}`} aria-label={`Confidence: ${confidenceText(confidence)}`}>{confidenceText(confidence)}</span>
      <span className="evidence-reason">{confidence.reason}</span>
      {confidence.calibration && <span className="evidence-reason">Calibration: {confidence.calibration.correct}/{confidence.calibration.n} · {confidence.calibration.source}</span>}
    </div>
    {onShowCalculation && reasoning.calc && <button type="button" className="evidence-calc-link" onClick={onShowCalculation}>Show calculation</button>}
    {confidence.improve && <p className="evidence-improve">To verify: {confidence.improve}</p>}
  </section>
}
