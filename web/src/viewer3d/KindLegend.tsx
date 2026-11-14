import { KIND_COLORS, kindCounts } from '../lib/kind-colors';
import './kind-legend.css';

/** Colour plus label plus count ("Windows 11 · Doors 11"): never relies on colour alone. */
export function KindLegend({ kinds, className = '' }: { kinds: readonly (string | null | undefined)[]; className?: string }) {
  const counts = kindCounts(kinds);
  if (!counts.length) return null;
  return <ul className={`kind-legend ${className}`} data-testid="kind-legend" aria-label="Item colours">
    {counts.map(({ key, count }) => <li key={key} data-kind={key} data-count={count}>
      <span className="kind-legend-swatch" aria-hidden="true" style={{ background: KIND_COLORS[key].color }} />
      <span>{KIND_COLORS[key].plural} {count}</span>
    </li>)}
  </ul>;
}
