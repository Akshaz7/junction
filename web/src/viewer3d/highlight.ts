import { Box3, Color, type Material, type Mesh, type Object3D } from 'three';
import type { LoadedScene } from './scene';

export interface HighlightOptions {
  /** CONTRACT 5.7 evidence.boxes labels, keyed by the same item_id. */
  labels?: Record<string, string>;
  cameraTargetItemId?: string;
  /** Isolation supplies its own dimming layer. */
  dimOthers?: boolean;
}

export interface HighlightState {
  highlighted: string[];
  /** Number of other resolved items, including items on hidden storeys. */
  dimmed: number;
  labels: Record<string, string>;
}

/** Uses actual rendered geometry, in the already-recentred CONTRACT 5.2 frame. */
export function itemBounds(scene: LoadedScene, ids: readonly string[]): Box3 {
  scene.root.updateWorldMatrix(true, true);
  const bounds = new Box3();
  for (const id of ids) {
    const object = scene.items.get(id);
    if (object) bounds.union(new Box3().setFromObject(object));
  }
  return bounds;
}

/** Reads the visible mode accent each time highlighting is requested. */
export function readHighlightColor(element: HTMLElement): Color {
  const fallback = '#166ed1';
  const token = getComputedStyle(element).getPropertyValue('--mode-accent').trim();
  if (!token || !CSS.supports('color', token)) return new Color(fallback);
  // Resolve CSS color syntax (including oklch/var()) to sRGB for three.js.
  const probe = document.createElement('span');
  probe.style.color = token;
  probe.style.display = 'none';
  element.parentElement?.append(probe);
  const resolved = getComputedStyle(probe).color;
  probe.remove();
  // Current tokens use hex, hence browsers return rgb(). Retain a safe fallback
  // if the browser preserves a newer color space three.js cannot parse.
  return new Color(/^rgba?\(/.test(resolved) ? resolved : /^#/.test(token) ? token : fallback);
}

/** Material ownership is isolated from WebGL/DOM so it can be tested directly. */
export function createHighlightController(scene: LoadedScene) {
  const originals = new Map<Mesh, Material | Material[]>();
  const clones = new Set<Material>();
  let state: HighlightState = { highlighted: [], dimmed: 0, labels: {} };

  function clearHighlight(): void {
    for (const [mesh, material] of originals) mesh.material = material;
    originals.clear();
    clones.forEach((material) => material.dispose());
    clones.clear();
    state = { highlighted: [], dimmed: 0, labels: {} };
  }

  return {
    highlight(ids: readonly string[], options: HighlightOptions = {}, accent = new Color('#166ed1')): void {
      clearHighlight();
      const selected = new Set(ids.filter((id) => scene.items.has(id)));
      if (!selected.size) return;
      const labels = Object.fromEntries([...selected].map((id, index) => [id, options.labels?.[id] ?? String(index + 1)]));
      state = { highlighted: [...selected], dimmed: scene.items.size - selected.size, labels };
      scene.root.traverse((object) => {
        const mesh = object as Mesh;
        if (!mesh.isMesh) return;
        // The textured drawing remains readable beneath the rising items.
        if (mesh.name === 'plan_floor') return;
        let owner: string | undefined;
        for (let current: Object3D | null = mesh; current; current = current.parent) {
          owner = scene.itemIdsByObject.get(current);
          if (owner) break;
        }
        const highlighted = owner !== undefined && selected.has(owner);
        originals.set(mesh, mesh.material);
        const modify = (material: Material): Material => {
          const clone = material.clone();
          clones.add(clone);
          const surface = clone as Material & { color?: Color; emissive?: Color; emissiveIntensity?: number };
          if (highlighted) {
            if (surface.emissive) {
              surface.emissive.copy(accent);
              surface.emissiveIntensity = 1.5;
            } else surface.color?.copy(accent);
          } else if (options.dimOthers !== false) {
            if (surface.color) {
              const gray = surface.color.r * 0.2126 + surface.color.g * 0.7152 + surface.color.b * 0.0722;
              surface.color.lerp(new Color().setRGB(gray, gray, gray), 0.85);
            }
            surface.emissive?.set(0);
            clone.opacity *= 0.18;
            clone.transparent = true;
            clone.depthWrite = false;
          }
          clone.needsUpdate = true;
          return clone;
        };
        mesh.material = Array.isArray(mesh.material) ? mesh.material.map(modify) : modify(mesh.material);
      });
    },
    clearHighlight,
    getHighlightState(): HighlightState {
      return { ...state, highlighted: [...state.highlighted], labels: { ...state.labels } };
    },
  };
}
