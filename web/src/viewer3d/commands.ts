/** move/material: the shared chat edit layer's Edit-panel what-ifs. They never change visibility state. */
export type SceneOperation = 'highlight' | 'hide' | 'restore' | 'reset' | 'isolate' | 'move' | 'material';
export interface SceneCommand {
  op: SceneOperation;
  item_ids: readonly string[];
  labels?: Readonly<Record<string, string>>;
  /** move: metres from the original spot (X, Z); [0, 0] puts the item back. */
  offset_m?: readonly [number, number];
  /** material: wall material name; null restores the original. */
  material?: string | null;
}
export interface CommandState {
  hidden: Set<string>;
  highlighted: Map<string, string>;
  isolated: Set<string> | null;
}
export interface SceneSnapshot {
  hidden: readonly string[];
  highlighted: readonly string[];
  labels: Readonly<Record<string, string>>;
  isolated?: readonly string[] | null;
  /** Shared layer: when present, the moves/materials the viewer should show (absent = leave local ones alone). */
  moved?: Readonly<Record<string, readonly [number, number]>>;
  materials?: Readonly<Record<string, string>>;
}

/** CONTRACT 5.11: only commands/snapshots fall back to document tags. */
export function resolveCommandLabels(
  ids: readonly string[], labels: Readonly<Record<string, string>> | undefined,
  items: Readonly<Record<string, { tag?: string }>>,
): Record<string, string> {
  return Object.fromEntries(ids.map((id) => [id, labels?.[id] ?? items[id]?.tag ?? id]));
}

export const emptyCommandState = (): CommandState => ({ hidden: new Set(), highlighted: new Map(), isolated: null });

/** Fold in arrival order. All collections are copied so earlier states remain usable. */
export function applyCommand(state: CommandState, cmd: SceneCommand): CommandState {
  if (cmd.op === 'reset') return emptyCommandState();
  const next: CommandState = {
    hidden: new Set(state.hidden), highlighted: new Map(state.highlighted),
    isolated: state.isolated === null ? null : new Set(state.isolated),
  };
  const ids = new Set(cmd.item_ids);
  switch (cmd.op) {
    case 'highlight':
      next.highlighted = new Map([...ids].map((id) => [id, cmd.labels?.[id] ?? id]));
      break;
    case 'hide':
      for (const id of ids) {
        next.hidden.add(id);
        next.highlighted.delete(id);
        next.isolated?.delete(id);
      }
      break;
    case 'restore':
      if (!ids.size) next.hidden.clear();
      else for (const id of ids) next.hidden.delete(id);
      break;
    case 'isolate':
      next.isolated = ids;
      next.highlighted = new Map([...ids].map((id) => [id, cmd.labels?.[id] ?? id]));
      for (const id of ids) next.hidden.delete(id);
      break;
  }
  return next;
}

/** A reconnect snapshot replaces the edit layer, including any previous isolation. */
export function applyState(snapshot: SceneSnapshot): CommandState {
  return {
    hidden: new Set(snapshot.hidden),
    highlighted: new Map(snapshot.highlighted.map((id) => [id, snapshot.labels[id] ?? id])),
    isolated: snapshot.isolated == null ? null : new Set(snapshot.isolated),
  };
}

export interface CommandTestState {
  hidden: string[];
  highlighted: Record<string, string>;
  isolated: string[] | null;
}
export function readCommandState(state: CommandState): CommandTestState {
  return {
    hidden: [...state.hidden], highlighted: Object.fromEntries(state.highlighted),
    isolated: state.isolated === null ? null : [...state.isolated],
  };
}
