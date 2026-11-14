import { useSyncExternalStore } from 'react';

export type LinkedSource = '2d' | '3d';
export interface LinkedItem {
  readonly hovered: string | null;
  readonly selected: string | null;
  readonly hoverSource: LinkedSource | null;
  readonly selectedSource: LinkedSource | null;
}

type Listener = (state: LinkedItem) => void;
let state: LinkedItem = Object.freeze({ hovered: null, selected: null, hoverSource: null, selectedSource: null });
const listeners = new Set<Listener>();

export function getLinkedItem(): LinkedItem { return state; }

function update(next: LinkedItem): void {
  if (Object.keys(next).every((key) => next[key as keyof LinkedItem] === state[key as keyof LinkedItem])) return;
  state = Object.freeze(next);
  for (const listener of [...listeners]) listener(state);
}

export function setHover(item_id: string | null, source: LinkedSource): void {
  // A late pointer-leave from one view must not erase the other view's hover.
  if (item_id === null && state.hoverSource !== source) return;
  update({ ...state, hovered: item_id, hoverSource: item_id === null ? null : source });
}

export function setSelected(item_id: string | null, source: LinkedSource): void {
  update({ ...state, selected: item_id, selectedSource: item_id === null ? null : source });
}

export function subscribe(fn: Listener): () => void {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}

/** React reads the same stable snapshot as non-React subscribers; never republish an echo. */
export function useLinkedItem(): LinkedItem {
  return useSyncExternalStore(subscribe, getLinkedItem, getLinkedItem);
}
