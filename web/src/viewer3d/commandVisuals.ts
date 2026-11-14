import type { Material, Mesh, Object3D } from 'three';
import type { LoadedScene } from './scene';
import { emptyCommandState, type CommandState } from './commands';
import { DIM_OPACITY } from './cinematic';

const ISOLATE_OPACITY = 0.18;
const ISOLATE_MS = 250;
/** A removed item the answer also highlights stays as a faint ghost (with its glow, outline and tag) instead of vanishing. */
export const GHOST_AMOUNT = 0.22;

/** Last material layer: never mutate the source, answer or local-selection materials. */
export function createCommandVisuals(scene: LoadedScene) {
  let state = emptyCommandState();
  const visibility = new Map<Object3D, boolean>();
  const amounts = new Map<string, number>();
  const fades = new Map<string, { from: number; to: number; start: number }>();
  const originals = new Map<Mesh, Material | Material[]>();
  const layers: { material: Material; opacity: number; id: string }[] = [];
  let dirty = true;
  // Isolate dims everything else; the level tweens so "show only the stairs" and "reset" fade rather than snap.
  let dimSet: ReadonlySet<string> | null = null;
  let dim = { from: 0, to: 0, start: 0, level: 0 };
  // Transient reveal: items outside `focus` sit at DIM_OPACITY * focusLevel while the answer is lit one by one.
  let focus: ReadonlySet<string> | null = null;
  let focusLevel = 0;
  const factor = (id: string) =>
    (dimSet && !dimSet.has(id) ? 1 - (1 - ISOLATE_OPACITY) * dim.level : 1)
    * (focus && !focus.has(id) ? 1 - (1 - DIM_OPACITY) * focusLevel : 1);
  const captureVisibility = () => {
    for (const object of scene.items.values()) visibility.set(object, object.visible);
    dirty = true;
  };
  captureVisibility();

  function clearMaterials() {
    for (const [mesh, material] of originals) mesh.material = material;
    originals.clear();
    for (const { material } of layers) material.dispose();
    layers.length = 0;
  }

  function sample(now: number) {
    const dimming = dim.level !== dim.to;
    if (!dirty && !fades.size && !dimming) return false;
    dirty = false;
    if (dimming) {
      const t = Math.max(0, Math.min(1, (now - dim.start) / ISOLATE_MS));
      dim.level = dim.from + (dim.to - dim.from) * t;
      if (t === 1) { dim.level = dim.to; if (dim.to === 0 && !state.isolated) { dimSet = null; rebuildMaterials(); } }
    }
    let completed = false;
    for (const [id, fade] of fades) {
      const t = Math.max(0, Math.min(1, (now - fade.start) / 250));
      amounts.set(id, fade.from + (fade.to - fade.from) * t);
      if (t === 1) { fades.delete(id); completed = true; }
    }
    if (completed) rebuildMaterials();
    for (const [id, object] of scene.items) {
      // Cutaway always wins, including during an interrupted fade.
      object.visible = visibility.get(object) !== false && (amounts.get(id) ?? 1) > 0;
    }
    for (const layer of layers) {
      layer.material.opacity = layer.opacity * (amounts.get(layer.id) ?? 1) * factor(layer.id);
    }
    return true;
  }

  function rebuildMaterials() {
    dirty = true;
    clearMaterials();
    scene.root.traverse((object) => {
      const mesh = object as Mesh;
      if (!mesh.isMesh || mesh.name === 'plan_floor') return;
      let id: string | undefined;
      for (let current: Object3D | null = mesh; current; current = current.parent) {
        id = scene.itemIdsByObject.get(current);
        if (id) break;
      }
      if (!id) return;
      const dimmed = (dimSet !== null && !dimSet.has(id)) || (focus !== null && !focus.has(id));
      if (!dimmed && !fades.has(id) && (amounts.get(id) ?? 1) === 1) return;
      originals.set(mesh, mesh.material);
      const clone = (material: Material) => {
        const copy = material.clone();
        const opacity = material.opacity;
        copy.transparent = true;
        copy.depthWrite = false;
        copy.opacity = opacity * (amounts.get(id!) ?? 1) * factor(id!);
        layers.push({ material: copy, opacity, id: id! });
        return copy;
      };
      mesh.material = Array.isArray(mesh.material) ? mesh.material.map(clone) : clone(mesh.material);
    });
  }

  return {
    captureVisibility, clearMaterials, rebuildMaterials, sample,
    /** Transient reveal dim: everything outside `ids` fades to DIM_OPACITY at level 1. `null` releases it. */
    setFocus(ids: ReadonlySet<string> | null, level: number) {
      const changed = (focus === null) !== (ids === null);
      focus = ids; focusLevel = level; dirty = true;
      if (changed) rebuildMaterials();
    },
    focusActive: () => focus !== null,
    setState(next: CommandState, now: number, reducedMotion: boolean) {
      sample(now);
      if (reducedMotion) {
        for (const [id, fade] of fades) amounts.set(id, fade.to);
        fades.clear();
      }
      for (const id of scene.items.keys()) {
        const wasHidden = state.hidden.has(id);
        const hidden = next.hidden.has(id);
        if (hidden === wasHidden) continue;
        const target = hidden ? (next.highlighted.has(id) ? GHOST_AMOUNT : 0) : 1;
        if (reducedMotion) { amounts.set(id, target); fades.delete(id); }
        else fades.set(id, { from: amounts.get(id) ?? 1, to: target, start: now });
      }
      const isolating = next.isolated !== null;
      if (isolating) dimSet = next.isolated;
      const target = isolating ? 1 : 0;
      if (target !== dim.to) dim = { from: dim.level, to: target, start: now, level: dim.level };
      if (reducedMotion) { dim = { from: target, to: target, start: now, level: target }; if (!isolating) dimSet = null; }
      state = next;
      rebuildMaterials();
      sample(now);
    },
    dispose() { clearMaterials(); fades.clear(); },
  };
}
