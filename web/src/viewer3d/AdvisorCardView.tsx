import { AlertTriangle, Info, Lightbulb } from 'lucide-react';
import { cardSeverity, type AdvisorCard } from './advisor';
import './advisor-card.css';

const LABEL = { violation: 'Violation', suggestion: 'Suggestion', info: 'Info' } as const;

/** One advisor card: severity colour (red violation, amber suggestion, grey info), body, rules checked, source. */
export function AdvisorCardView({ card, className = '', onHighlight }: {
  card: AdvisorCard; className?: string; onHighlight?: (ids: string[]) => void;
}) {
  const severity = cardSeverity(card);
  const Icon = severity === 'violation' ? AlertTriangle : severity === 'suggestion' ? Lightbulb : Info;
  const head = <>
    <span><Icon size={16} aria-label={LABEL[severity]} /><strong>{card.title}</strong><span className="advisor-severity">{LABEL[severity]}</span></span>
    <span>{card.body}</span>
  </>;
  return <article className={`viewer3d-advisor-card ${className}`.trim()} data-advisor-card={card.card_id} data-kind={card.kind} data-severity={severity}>
    {onHighlight
      ? <button type="button" className="viewer3d-advisor-select" onClick={() => onHighlight(card.item_ids)} aria-label={`Highlight: ${card.title}`}>{head}</button>
      : <div className="viewer3d-advisor-select">{head}</div>}
    {!!card.checked?.length && <p className="advisor-checked" data-testid="advisor-checked">Checked: {card.checked.join(', ')}</p>}
    <details><summary>{card.source.title}</summary><blockquote>{card.source.quote}</blockquote></details>
  </article>;
}
