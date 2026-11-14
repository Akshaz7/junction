import type { Answer, Citation } from '../lib/types'
import { edgeVerb } from '../lib/kg'
import './evidence-card.css'

/** The project this chat belongs to, read from the address (chat inside a project). */
function hashProject() {
  return new URLSearchParams(window.location.hash.split('?')[1] ?? '').get('project')
}

function GraphPath({ path }: { path: NonNullable<NonNullable<Answer['reasoning']>['graph_path']> }) {
  const project = hashProject()
  // Exact node ids when the answer carries them; labels remain the fallback for older answers.
  const labels = [...new Set(path.flatMap((step) => [step.from_id || step.from_label, step.to_id || step.to_label]))]
  return <div className="evidence-path" aria-label="Links followed in the project graph">
    <h4>Links followed</h4>
    <ol>{path.map((step, index) => <li key={index}><span>{step.from_label}</span><em>{edgeVerb(step.edge_kind)}</em><span>{step.to_label}</span></li>)}</ol>
    {project && <a href={`#/projects?id=${encodeURIComponent(project)}&tab=graph&focus=${encodeURIComponent(labels.join('|'))}`}>View in graph</a>}
  </div>
}

/** "How we know": the steps behind an answer and how sure we are. Steps with a citation open it. */
export function EvidenceCard({ answer, selected, onOpenCitation }: { answer: Answer; selected?: Citation; onOpenCitation: (citation: Citation) => void }) {
  const reasoning = answer.reasoning
  if (!reasoning?.steps?.length) return null
  const { confidence } = reasoning
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
    {!!reasoning.graph_path?.length && <GraphPath path={reasoning.graph_path} />}
    <div className="evidence-confidence">
      <span className={`evidence-pill ${tone}`} aria-label={`Confidence: ${confidence.label}, ${confidence.pct} percent`}>{confidence.label} · {confidence.pct}%</span>
      <span className="evidence-reason">{confidence.reason}</span>
    </div>
    {confidence.improve && <p className="evidence-improve">To make it exact: {confidence.improve}</p>}
  </section>
}
