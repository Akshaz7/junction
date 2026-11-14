import { KIND_COLORS, kindCounts } from '../lib/kind-colors';
import './kind-legend.css';

/** Colour plus label plus count ("Windows 11 · Doors 11"): never relies on colour alone. */
export function KindLegend({ kinds, totals, className = '' }: { kinds: readonly (string | null | undefined)[]; /** Kinds of every item in the answer: the total leads, this page's count follows. */ totals?: readonly (string | null | undefined)[]; className?: string }) {
  const totalOf = new Map(totals ? kindCounts(totals).map(({ key, count }) => [key, count]) : []);
  const rooms = new Map<string, number>();
  for (const kind of kinds) if (kind?.startsWith('room:')) rooms.set(kind.slice(5), (rooms.get(kind.slice(5)) ?? 0) + 1);
  const sizes = new Map<string, number>();
  for (const kind of kinds) if (kind?.startsWith('size:')) sizes.set(kind.slice(5), (sizes.get(kind.slice(5)) ?? 0) + 1);
  const counts = kindCounts(kinds.filter((kind) => !kind?.startsWith('room:') && !kind?.startsWith('size:')));
  if (!counts.length && !rooms.size && !sizes.size) return null;
  return <ul className={`kind-legend ${className}`} data-testid="kind-legend" aria-label="Item colours">
    {counts.map(({ key, count }) => {
      const total = Math.max(totalOf.get(key) ?? count, count);
      return <li key={key} data-kind={key} data-count={total}>
        <span className="kind-legend-swatch" aria-hidden="true" style={{ background: KIND_COLORS[key].color }} />
        <span>{KIND_COLORS[key].plural} {total}{total > count && <small className="kind-legend-page"> · this page {count}</small>}</span>
      </li>;
    })}
    {[...sizes].sort().map(([label, count]) => <li key={`size:${label}`} data-kind="pipe" data-count={count}>
      <span className="kind-legend-swatch" aria-hidden="true" style={{ background: KIND_COLORS.pipe.color }} />
      <span>{label} pipes {count}</span>
    </li>)}
    {[...rooms].map(([label, count]) => <li key={`room:${label}`} data-kind="room" data-count={count}>
      <span className="kind-legend-swatch" aria-hidden="true" style={{ background: KIND_COLORS.room.color }} />
      <span>{label} {count}</span>
    </li>)}
  </ul>;
}
