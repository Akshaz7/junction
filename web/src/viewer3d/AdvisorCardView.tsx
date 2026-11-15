import { AlertTriangle, ExternalLink, Info, Lightbulb } from 'lucide-react';
import { cardSeverity, type AdvisorCard } from './advisor';
import './advisor-card.css';

const LABEL = { violation: 'Violation', suggestion: 'Suggestion', info: 'Info' } as const;

const RULE_NAMES: Record<string, string> = {
  'fi-acc-door-clear-width': 'Door width (241/2017 §4)',
  'fi-acc-entrance-level-change-ramp': 'Entrance ramp (241/2017 §2)',
  'fi-acc-corridor-turning-space': 'Corridor turning space (241/2017 §5)',
  'fi-fire-exit-width': 'Exit width (848/2017 §34)',
  'fi-fire-exits-per-storey': 'Exits per storey (848/2017 §33)',
  'fi-use-headroom': 'Headroom (1007/2017 §14)',
};
/** Human rule name for a rule id; unknown ids lose the prefix and dashes. */
export const ruleName = (id: string) => RULE_NAMES[id] ?? id.replace(/^fi-(acc|fire|use)-/, '').replace(/-/g, ' ');
/** "Decree … 848/2017 (…), 34 §" -> "Decree 848/2017 §34". */
export const shortSource = (title: string) => {
  const decree = title.match(/\b(\d{3,4}\/\d{4})\b/)?.[1];
  const section = title.match(/(\d+)\s*§|§\s*(\d+)/);
  const sec = section?.[1] ?? section?.[2];
  return decree ? `Decree ${decree}${sec ? ` §${sec}` : ''}` : title;
};

const httpUrl = (url?: string | null) => (url && /^https?:\/\//i.test(url) ? url : undefined);
/** Name the publisher so the reader knows where the link goes before clicking it. */
export const sourceLinkLabel = (url: string) => {
  const host = (() => { try { return new URL(url).hostname; } catch { return ''; } })();
  if (host.endsWith('finlex.fi')) return 'Finlex: legal text (Finnish)';
  if (host.endsWith('ec.europa.eu')) return 'Official English text (EU TRIS)';
  if (host.endsWith('ym.fi')) return 'Ministry of the Environment (English)';
  return host || 'Official source';
};
/** Official links for a card's rule: the English text first, then the Finnish legal text when it differs. */
export const sourceLinks = (source: AdvisorCard['source']) =>
  [...new Set([httpUrl(source.url), httpUrl(source.finnish_url)].filter((u): u is string => !!u))];
/** Short source label; adds the card's own section when the title has none. */
export const sourceLabel = (source: AdvisorCard['source']) => {
  const short = shortSource(source.title);
  const section = source.section?.trim();
  if (!section || short.includes('§')) return short;
  return `${short} ${/^\d/.test(section) ? `§${section}` : section}`;
};

/** One advisor card: severity colour (red violation, amber suggestion, grey info), body, rules checked, source. */
export function AdvisorCardView({ card, className = '', onHighlight }: {
  card: AdvisorCard; className?: string; onHighlight?: (ids: string[]) => void;
}) {
  const severity = cardSeverity(card);
  const Icon = severity === 'violation' ? AlertTriangle : severity === 'suggestion' ? Lightbulb : Info;
  const label = sourceLabel(card.source);
  const head = <>
    <span><Icon size={16} aria-label={LABEL[severity]} /><strong>{card.title}</strong><span className="advisor-severity">{LABEL[severity]}</span></span>
    <span>{card.body}</span>
  </>;
  return <article className={`viewer3d-advisor-card ${className}`.trim()} data-advisor-card={card.card_id} data-kind={card.kind} data-severity={severity}>
    {onHighlight
      ? <button type="button" className="viewer3d-advisor-select" onClick={() => onHighlight(card.item_ids)} aria-label={`Highlight: ${card.title}`}>{head}</button>
      : <div className="viewer3d-advisor-select">{head}</div>}
    {!!card.checked?.length && <p className="advisor-checked" data-testid="advisor-checked">Checked: {card.checked.map(ruleName).join(' · ')}</p>}
    <details><summary title={card.source.title}>{label}</summary><blockquote>{card.source.quote}</blockquote></details>
    {!!sourceLinks(card.source).length && <p className="advisor-links" data-testid="advisor-source-links">
      {sourceLinks(card.source).map((url) => <a key={url} href={url} target="_blank" rel="noreferrer">{sourceLinkLabel(url)} <ExternalLink size={12} aria-hidden /></a>)}
    </p>}
  </article>;
}
