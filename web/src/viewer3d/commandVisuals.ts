import type { Material, Mesh, Object3D } from 'three';
import type { LoadedScene } from './scene';
import { emptyCommandState, type CommandState } from './commands';

/** Last material layer: never mutate the source, answer or local-selection materials. */
export function createCommandVisuals(scene: LoadedScene) {
  let state = emptyCommandState();
  const visibility = new Map<Object3D, boolean>();
  const amounts = new Map<string, number>();
  const fades = new Map<string, { from: number; to: number; start: number }>();
  const originals = new Map<Mesh, Material | Material[]>();
  const layers: { material: Material; opacity: number; id: string }[] = [];
  let dirty = true;
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
    if (!dirty && !fades.size) return false;
    dirty = false;
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
      layer.material.opacity = layer.opacity * (amounts.get(layer.id) ?? 1);
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
      const dim = state.isolated !== null && !state.isolated.has(id);
      if (!dim && !fades.has(id) && (amounts.get(id) ?? 1) === 1) return;
      originals.set(mesh, mesh.material);
      const clone = (material: Material) => {
        const copy = material.clone();
        const opacity = material.opacity * (dim ? 0.18 : 1);
        copy.transparent = true;
        copy.depthWrite = false;
        copy.opacity = opacity * (amounts.get(id!) ?? 1);
        layers.push({ material: copy, opacity, id: id! });
        return copy;
      };
      mesh.material = Array.isArray(mesh.material) ? mesh.material.map(clone) : clone(mesh.material);
    });
  }

  return {
    captureVisibility, clearMaterials, rebuildMaterials, sample,
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
        const target = hidden ? 0 : 1;
        if (reducedMotion) { amounts.set(id, target); fades.delete(id); }
        else fades.set(id, { from: amounts.get(id) ?? 1, to: target, start: now });
      }
      state = next;
      rebuildMaterials();
      sample(now);
    },
    dispose() { clearMaterials(); fades.clear(); },
  };
}
