import { useEffect, useRef } from 'react';
import type { ItemDetails } from './identify';

export function ItemDetailsCard({ details, loading, onClose }: {
  details: ItemDetails; loading: boolean; onClose: () => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
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

  return <aside className="viewer3d-item-card" aria-label="Item details"
    data-item-id={details.item_id}>
    <div className="viewer3d-item-card-heading">
      <h2>{details.name}</h2>
      <button ref={closeRef} type="button" aria-label="Close item details" onClick={onClose}>×</button>
    </div>
    <dl>{details.fields.map(({ label, value }) => <div key={label}>
      <dt>{label}</dt><dd>{value}</dd>
    </div>)}</dl>
    {details.name !== details.item_id && <p className="viewer3d-item-id">{details.item_id}</p>}
    {!details.hasElement && <p className="viewer3d-item-note" role="status">
      {loading ? 'Loading properties…' : 'No additional properties available.'}
    </p>}
  </aside>;
}
