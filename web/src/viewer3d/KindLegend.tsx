import { KIND_COLORS, kindCounts } from '../lib/kind-colors';
import './kind-legend.css';

/** Colour plus label plus count ("Windows 11 · Doors 11"): never relies on colour alone. */
export function KindLegend({ kinds, className = '' }: { kinds: readonly (string | null | undefined)[]; className?: string }) {
  const rooms = new Map<string, number>();
  for (const kind of kinds) if (kind?.startsWith('room:')) rooms.set(kind.slice(5), (rooms.get(kind.slice(5)) ?? 0) + 1);
  const counts = kindCounts(kinds.filter((kind) => !kind?.startsWith('room:')));
  if (!counts.length && !rooms.size) return null;
  return <ul className={`kind-legend ${className}`} data-testid="kind-legend" aria-label="Item colours">
    {counts.map(({ key, count }) => <li key={key} data-kind={key} data-count={count}>
      <span className="kind-legend-swatch" aria-hidden="true" style={{ background: KIND_COLORS[key].color }} />
      <span>{KIND_COLORS[key].plural} {count}</span>
    </li>)}
    {[...rooms].map(([label, count]) => <li key={`room:${label}`} data-kind="room" data-count={count}>
      <span className="kind-legend-swatch" aria-hidden="true" style={{ background: KIND_COLORS.room.color }} />
      <span>{label} {count}</span>
    </li>)}
  </ul>;
}
