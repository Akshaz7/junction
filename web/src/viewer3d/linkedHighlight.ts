import { Color, type Material, type Mesh, type Object3D } from 'three';
import type { LoadedScene } from './scene';

/** A local material layer above answer/live highlights. Hover never broadcasts or moves the camera. */
export function createLinkedHighlightController(scene: LoadedScene) {
  const source = new Map<Mesh, Material | Material[]>();
  const underneath = new Map<Mesh, Material | Material[]>();
  const clones = new Set<Material>();
  scene.root.traverse((object) => {
    const mesh = object as Mesh;
    if (mesh.isMesh) source.set(mesh, mesh.material);
  });

  function clear(): void {
    for (const [mesh, material] of underneath) mesh.material = material;
    underneath.clear();
    clones.forEach((material) => material.dispose());
    clones.clear();
  }

  return {
    clear,
    apply(hovered: string | null, selected: string | null, accent: Color): void {
      clear();
      for (const [mesh, original] of source) {
        let owner: string | undefined;
        for (let current: Object3D | null = mesh; current; current = current.parent) {
          owner = scene.itemIdsByObject.get(current);
          if (owner) break;
        }
        if (!owner || (owner !== hovered && owner !== selected)) continue;
        underneath.set(mesh, mesh.material);
        const modify = (material: Material) => {
          const clone = material.clone();
          clones.add(clone);
          const surface = clone as Material & { color?: Color; emissive?: Color; emissiveIntensity?: number };
          if (surface.emissive) {
            surface.emissive.copy(accent);
            surface.emissiveIntensity = owner === selected ? 2.5 : 0.45;
          } else surface.color?.lerp(accent, owner === selected ? 0.9 : 0.3);
          clone.needsUpdate = true;
          return clone;
        };
        mesh.material = Array.isArray(original) ? original.map(modify) : modify(original);
      }
    },
  };
}
