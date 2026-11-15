import { useEffect, useRef } from 'react';
import type { ItemDetails } from './identify';
import type { Viewer } from './viewer';
import { WallDetails } from '../components/wall-details';

export function ItemDetailsCard({ details, loading, viewer, onClose, onHighlight }: {
  details: ItemDetails; loading: boolean; onClose: () => void; onHighlight: () => void;
  viewer: Viewer | null;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const cardRef = useRef<HTMLElement>(null);
  useEffect(() => {
    let frame = 0;
    function position() {
      const card = cardRef.current;
      const stage = card?.parentElement;
      const point = viewer?.itemScreenPosition(details.item_id);
      if (card && stage && point) {
        // Keep the callout readable even when its anchor is near a viewport edge.
        const left = Math.max(12, Math.min(stage.clientWidth - card.offsetWidth - 12, point.x + 24));
        const top = Math.max(12, Math.min(stage.clientHeight - card.offsetHeight - 12, point.y - card.offsetHeight / 2));
        card.style.left = `${left}px`;
        card.style.top = `${top}px`;
        card.style.visibility = point.visible ? 'visible' : 'hidden';
        card.dataset.anchored = 'true';
      }
      frame = requestAnimationFrame(position);
    }
    position();
    return () => cancelAnimationFrame(frame);
  }, [viewer, details.item_id]);
  useEffect(() => {
    const previous = document.activeElement;
    closeRef.current?.focus({ preventScroll: true });
    function escape(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
      }
    }
    window.addEventListener('keydown', escape);
    return () => {
      window.removeEventListener('keydown', escape);
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus({ preventScroll: true });
    };
  }, [onClose]);

  return <aside ref={cardRef} className="viewer3d-item-card" aria-label="Item details"
    data-item-id={details.item_id}>
    <div className="viewer3d-item-card-heading">
      <h2>{details.name}</h2>
      <button ref={closeRef} type="button" aria-label="Close item details" onClick={onClose}>×</button>
    </div>
    <dl>{details.fields.map(({ label, value }) => <div key={label}>
      <dt>{label}</dt><dd>{value}</dd>
    </div>)}</dl>
    {details.wall && <WallDetails wall={details.wall} />}
    {details.askHref && <a className="wall-ask" href={details.askHref}>Ask about this wall</a>}
    {!details.hasElement && <p className="viewer3d-item-note" role="status">
      {loading ? 'Loading properties…' : 'No additional properties available.'}
    </p>}
    <button type="button" onClick={onHighlight}>Highlight</button>
  </aside>;
}
