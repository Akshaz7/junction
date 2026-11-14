import { useEffect, useRef, useState } from 'react';
import { AdvisorCardView } from './AdvisorCardView';
import { createAdvisorRequests, type AdvisorCard } from './advisor';
import { onAdvisorCards } from './liveHighlight';
import { WALL_MATERIALS, type EditState, type ItemEdit, type WallMaterial } from './edits';
import type { SceneManifest } from './scene';

export function useEditAdvisor(doc_id?: string, chat_id?: string) {
  const [cards, setCards] = useState<AdvisorCard[]>([]);
  const [status, setStatus] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const requests = useRef<ReturnType<typeof createAdvisorRequests> | null>(null);
  useEffect(() => {
    setCards([]); setStatus('idle');
    if (!doc_id) return;
    const client = createAdvisorRequests({ doc_id, chat_id,
      onLoading() { setCards([]); setStatus('loading'); },
      onCards(next) { setCards(next); setStatus('ready'); },
      onError() { setCards([]); setStatus('error'); },
    });
    requests.current = client;
    const stop = onAdvisorCards(client.receive);
    return () => { stop(); client.dispose(); if (requests.current === client) requests.current = null; };
  }, [doc_id, chat_id]);
  return { cards, status, enqueue(edit: ItemEdit | null) { if (edit) requests.current?.enqueue(edit); } };
}

/** Optional "Save as new version": keeps the edited design as a new version of the document (original untouched). */
export interface SaveVersionControl { canSave: boolean; busy: boolean; message?: string; href?: string; onSave(): void }

export function EditPanel({ selected, manifest, edits, moving, advice, hidden = [], onRemove, onMove, onMaterial, onUndo, onReset, onRestore, onHighlight, save }: {
  selected: string | null;
  manifest: SceneManifest;
  edits: EditState;
  moving: boolean;
  advice: ReturnType<typeof useEditAdvisor>;
  /** Hidden items in the shared layer: removed here or by the chat. */
  hidden?: readonly string[];
  onRemove(): void;
  onMove(): void;
  onMaterial(material: WallMaterial): void;
  onUndo(): void;
  onReset(): void;
  onRestore?(ids: string[]): void;
  onHighlight(ids: string[]): void;
  save?: SaveVersionControl;
}) {
  const item = selected ? manifest.items[selected] : null;
  const label = item?.tag ?? selected;
  return <aside className="viewer3d-edit-panel" aria-label="Edit items">
    <div className="viewer3d-edit-actions">
      <strong>{selected ? `Selected: ${label}` : 'Select an item to edit'}</strong>
      <button type="button" disabled={!selected} onClick={onRemove}>Remove</button>
      <button type="button" disabled={!selected} aria-pressed={moving} onClick={onMove}>Move</button>
      {selected && item?.kind === 'wall' && <label>Change material
        <select aria-label="Change material" value={edits.materials[selected] ?? ''}
          onChange={(event) => { if (event.target.value) onMaterial(event.target.value as WallMaterial); }}>
          <option value="" disabled>Original material</option>
          {Object.keys(WALL_MATERIALS).map((name) => <option key={name}>{name}</option>)}
        </select>
      </label>}
      <button type="button" disabled={!edits.undoCount} onClick={onUndo}>Undo</button>
      <button type="button" disabled={!edits.undoCount && !hidden.length} onClick={onReset}>Reset edits</button>
      {save && <button type="button" disabled={!save.canSave || save.busy} onClick={save.onSave}
        title="Keep this edited design as a new version of the document. The original is not changed.">{save.busy ? 'Saving…' : 'Save as new version'}</button>}
    </div>
    {onRestore && hidden.length > 0 && <div className="viewer3d-edit-removed" aria-label="Removed items">
      <span>Removed ({hidden.length}):</span>
      {hidden.slice(0, 12).map((id) => <button key={id} type="button" aria-label={`Restore ${manifest.items[id]?.tag ?? id}`}
        onClick={() => onRestore([id])}>{manifest.items[id]?.tag ?? id} ↺</button>)}
      {hidden.length > 1 && <button type="button" onClick={() => onRestore([...hidden])}>Restore all</button>}
    </div>}
    {save?.message && <p role="status">{save.message}{save.href && <> <a href={save.href}>Compare with the original</a></>}</p>}
    {selected && edits.materials[selected] && <p>Material: {edits.materials[selected]}</p>}
    {moving && <p role="status">Drag on the model to move the selected item. Snaps to 0.1 m. Escape cancels.</p>}
    <div className="viewer3d-advisor" aria-label="Advice for this change" aria-live="polite">
      {advice.status === 'loading' && <p role="status">Checking this change…</p>}
      {advice.status === 'error' && <p role="status">Advice is unavailable for this change.</p>}
      {advice.status === 'ready' && !advice.cards.length && <p role="status">No advice for this change.</p>}
      {advice.cards.map((card) => <AdvisorCardView key={card.card_id} card={card} onHighlight={onHighlight} />)}
    </div>
  </aside>;
}
