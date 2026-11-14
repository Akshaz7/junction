import { Vector3, type Color, type Material, type Mesh } from 'three';
import type { LoadedScene } from './scene';
import { applyCommand, readCommandState, type CommandState, type SceneCommand } from './commands';

export const WALL_MATERIALS = {
  Concrete: '#a8aaa6',
  'Timber frame': '#bd946a',
  Glass: '#a2d4df',
} as const;
export type WallMaterial = keyof typeof WALL_MATERIALS;
export interface ItemEdit {
  op: 'hide' | 'move' | 'material' | 'restore' | 'reset';
  item_ids: string[];
  detail: Record<string, unknown>;
}
export interface EditState {
  undoCount: number;
  moved: Record<string, [number, number, number]>;
  /** Metres moved from the original spot, world X/Z (east, south). */
  moveDelta?: Record<string, [number, number]>;
  materials: Record<string, WallMaterial>;
}
type Surface = Material & { color?: Color };
/** `stale` entries no longer change anything (e.g. the chat already restored the item): Undo skips them. */
type History = { undo: () => ItemEdit; stale?: () => boolean; visibility?: true };

export const snapMetres = (value: number) => Math.round(value * 10) / 10;

/** Owns only local transforms/material clones. Visibility uses the existing command path. */
export function createEditLayer(scene: LoadedScene, commands: {
  apply(command: SceneCommand): void;
  hidden(): readonly string[];
}) {
  const positions = new Map<string, Vector3>();
  const materials = new Map<string, WallMaterial>();
  const originals = new Map<Mesh, Material | Material[]>();
  const clones = new Set<Material>();
  const history: History[] = [];
  let deferred: SceneCommand[] | null = null;
  function apply(command: SceneCommand) {
    if (deferred) deferred.push(command);
    else commands.apply(command);
  }

  function material(id: string, choice: WallMaterial | null) {
    scene.items.get(id)?.traverse((object) => {
      const mesh = object as Mesh;
      if (!mesh.isMesh) return;
      if (!originals.has(mesh)) originals.set(mesh, mesh.material);
      const previous = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
      for (const entry of previous) if (clones.delete(entry)) entry.dispose();
      const original = originals.get(mesh)!;
      const swap = (entry: Material) => {
        const copy = entry.clone() as Surface;
        copy.color?.set(WALL_MATERIALS[choice!]);
        clones.add(copy);
        return copy;
      };
      mesh.material = choice === null ? original : Array.isArray(original) ? original.map(swap) : swap(original);
    });
    if (choice === null) materials.delete(id);
    else materials.set(id, choice);
  }

  const isHidden = (id: string) => commands.hidden().includes(id);
  const live = () => history.filter((entry) => !entry.stale?.());
  const state = (): EditState => ({ undoCount: live().length,
    moved: Object.fromEntries([...positions.keys()].map((id) => [id, scene.items.get(id)!.position.toArray()])),
    moveDelta: Object.fromEntries([...positions.entries()].map(([id, from]) => {
      const now = scene.items.get(id)!.position; return [id, [now.x - from.x, now.z - from.z]];
    }).filter(([, d]) => Math.abs((d as number[])[0]) + Math.abs((d as number[])[1]) > 1e-6)),
    materials: Object.fromEntries(materials),
  });

  function recordState(before: CommandState, after: CommandState, command?: SceneCommand) {
    const previous = readCommandState(before);
    const next = readCommandState(after);
    const sameIds = (a: string[], b: string[]) => a.length === b.length && a.every((id) => b.includes(id));
    if (sameIds(previous.hidden, next.hidden) && (previous.isolated === null ? next.isolated === null
      : next.isolated !== null && sameIds(previous.isolated, next.isolated))) return;
    const hidden = previous.hidden;
    const isolated = previous.isolated;
    const highlighted = Object.keys(previous.highlighted);
    history.push({ undo: () => {
      // Invert ordinary removals without changing unrelated hidden items.
      if (command?.op === 'hide' && isolated === null && next.isolated === null) {
        const restored = next.hidden.filter((id) => !hidden.includes(id));
        apply({ op: 'restore', item_ids: restored });
        return { op: 'restore', item_ids: restored, detail: { undo: 'hide' } };
      }
      apply({ op: 'reset', item_ids: [] });
      if (hidden.length) apply({ op: 'hide', item_ids: hidden });
      if (isolated !== null) apply({ op: 'isolate', item_ids: isolated, labels: previous.highlighted });
      if (highlighted.length || isolated !== null) apply({ op: 'highlight', item_ids: highlighted, labels: previous.highlighted });
      return { op: 'restore', item_ids: command?.item_ids.slice() ?? next.hidden.filter((id) => !hidden.includes(id)), detail: { undo: command?.op ?? 'scene state' } };
    } });
  }

  return {
    state,
    /** Typed/remote edits share the viewer's Undo stack with panel edits. */
    recordCommand(command: SceneCommand, before: CommandState) {
      if (command.op === 'highlight') return;
      recordState(before, applyCommand(before, command), command);
    },
    recordState,
    remove(id: string): ItemEdit | null {
      if (!scene.items.has(id) || commands.hidden().includes(id)) return null;
      apply({ op: 'hide', item_ids: [id] });
      history.push({ undo: () => {
        apply({ op: 'restore', item_ids: [id] });
        return { op: 'restore', item_ids: [id], detail: { undo: 'hide' } };
      }, stale: () => !isHidden(id), visibility: true });
      return { op: 'hide', item_ids: [id], detail: {} };
    },
    /** Bring back items hidden by anyone (this panel or the chat). Undo hides them again. */
    restore(ids: readonly string[]): ItemEdit | null {
      const back = [...new Set(ids)].filter(isHidden);
      if (!back.length) return null;
      apply({ op: 'restore', item_ids: back });
      history.push({ undo: () => {
        const again = back.filter((id) => !isHidden(id));
        if (again.length) apply({ op: 'hide', item_ids: again });
        return { op: 'hide', item_ids: again, detail: { undo: 'restore' } };
      }, stale: () => back.every(isHidden), visibility: true });
      return { op: 'restore', item_ids: back, detail: {} };
    },
    /** A hide that came from outside this panel (chat command, other client, saved chat state) joins the
     * same Undo/Reset history, so a chat removal can be undone by hand. */
    noteExternalHide(ids: readonly string[]) {
      const gone = [...new Set(ids)];
      if (!gone.length) return;
      history.push({ undo: () => {
        const back = gone.filter(isHidden);
        if (back.length) apply({ op: 'restore', item_ids: back });
        return { op: 'restore', item_ids: back, detail: { undo: 'hide', external: true } };
      }, stale: () => !gone.some(isHidden), visibility: true });
    },
    /** Preview/commit a displacement in world X/Z; parent transforms stay intact. */
    move(id: string, from: Vector3, dx: number, dz: number, commit: boolean): ItemEdit | null {
      const object = scene.items.get(id);
      if (!object || !Number.isFinite(dx) || !Number.isFinite(dz)) return null;
      const x = snapMetres(dx), z = snapMetres(dz);
      const target = object.parent ? object.parent.localToWorld(from.clone()) : from.clone();
      target.x += x; target.z += z;
      object.position.copy(object.parent ? object.parent.worldToLocal(target) : target);
      object.updateWorldMatrix(true, true);
      if (!commit || (!x && !z)) return null;
      if (!positions.has(id)) positions.set(id, from.clone());
      history.push({ undo: () => {
        object.position.copy(from);
        if (object.position.equals(positions.get(id)!)) positions.delete(id);
        return { op: 'move', item_ids: [id], detail: { undo: true, position_m: object.getWorldPosition(new Vector3()).toArray() } };
      } });
      return { op: 'move', item_ids: [id], detail: { delta_m: [x, 0, z], position_m: object.getWorldPosition(new Vector3()).toArray() } };
    },
    changeMaterial(id: string, choice: WallMaterial): ItemEdit | null {
      if (!scene.items.has(id) || scene.manifest.items[id]?.kind !== 'wall'
        || !Object.hasOwn(WALL_MATERIALS, choice) || materials.get(id) === choice) return null;
      const previous = materials.get(id) ?? null;
      material(id, choice);
      history.push({ undo: () => {
        material(id, previous);
        return { op: 'material', item_ids: [id], detail: { material: previous, undo: true } };
      } });
      return { op: 'material', item_ids: [id], detail: { material: choice } };
    },
    undo(): ItemEdit | null {
      while (history.length && history[history.length - 1].stale?.()) history.pop();
      return history.pop()?.undo() ?? null;
    },
    /** Undo every move/material edit, then bring back everything hidden (by this panel or the chat). */
    reset(): ItemEdit | null {
      const hidden = commands.hidden();
      if (!live().length && !hidden.length) { history.length = 0; return null; }
      const affected = new Set<string>();
      // Restore every base material before the visibility command rebuilds the
      // highlight layers; otherwise their saved references resurrect old swaps.
      const pending: SceneCommand[] = [];
      deferred = pending;
      try {
        while (history.length) {
          const entry = history.pop()!;
          if (!entry.visibility && !entry.stale?.()) for (const id of entry.undo().item_ids) affected.add(id);
        }
      } finally { deferred = null; }
      for (const command of pending) commands.apply(command);
      if (hidden.length) {
        commands.apply({ op: 'restore', item_ids: hidden.length <= 500 ? [...hidden] : [] });
        for (const id of hidden) affected.add(id);
      }
      return { op: 'reset', item_ids: [...affected].slice(0, 200), detail: { local_edits: true } };
    },
    dispose() {
      for (const [mesh, original] of originals) mesh.material = original;
      for (const clone of clones) clone.dispose();
      clones.clear(); originals.clear(); history.length = 0;
    },
  };
}
