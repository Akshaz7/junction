import { Box3, Color, EdgesGeometry, LineBasicMaterial, LineSegments, type Material, type Mesh, type Object3D } from 'three';
import type { LoadedScene } from './scene';

const GLOW_INTENSITY = 2.8;

export interface HighlightOptions {
  /** CONTRACT 5.7 evidence.boxes labels, keyed by the same item_id. */
  labels?: Record<string, string>;
  cameraTargetItemId?: string;
  /** Retained for callers; answer highlighting always preserves other materials. */
  dimOthers?: boolean;
  /** Play the reveal (orbit, dim, one-by-one pulse) when this is a new answer in an open view. */
  cinematic?: boolean;
}

export interface HighlightState {
  highlighted: string[];
  /** Legacy count of other resolved items (their materials remain unchanged). */
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

export const HIGHLIGHT_AMBER = '#f5a623';

/** Evidence uses amber independently of the surrounding UI's mode accent. */
export function readHighlightColor(_element: HTMLElement): Color { return new Color(HIGHLIGHT_AMBER); }

/** Material ownership is isolated from WebGL/DOM so it can be tested directly. */
export function createHighlightController(scene: LoadedScene) {
  const originals = new Map<Mesh, Material | Material[]>();
  const clones = new Set<Material>();
  let state: HighlightState = { highlighted: [], dimmed: 0, labels: {} };
  /** Emissive surfaces per answer item, with their settled intensity, so a reveal can pulse them. */
  const glows = new Map<string, { surface: { emissiveIntensity?: number }; base: number }[]>();

  const outlines: LineSegments[] = [];

  function clearHighlight(): void {
    for (const line of outlines) { line.removeFromParent(); line.geometry.dispose(); (line.material as Material).dispose(); }
    outlines.length = 0;
    glows.clear();
    for (const [mesh, material] of originals) mesh.material = material;
    originals.clear();
    clones.forEach((material) => material.dispose());
    clones.clear();
    state = { highlighted: [], dimmed: 0, labels: {} };
  }

  return {
    /** `accent` is one colour for all ids, or a per-id resolver (the fixed per-kind colours). */
    highlight(ids: readonly string[], options: HighlightOptions = {}, accent: Color | ((id: string) => Color) = new Color(HIGHLIGHT_AMBER)): void {
      clearHighlight();
      const selected = new Set(ids.filter((id) => scene.items.has(id)));
      if (!selected.size) return;
      // Answer/live evidence keeps its citation numbers even in a tagged scene.
      // Commands resolve their tags before entering this controller.
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
        if (!highlighted) return;
        originals.set(mesh, mesh.material);
        const color = typeof accent === 'function' ? accent(owner!) : accent;
        const modify = (material: Material): Material => {
          const clone = material.clone();
          clones.add(clone);
          const surface = clone as Material & { color?: Color; emissive?: Color; emissiveIntensity?: number };
          if (highlighted) {
            // Blueprint glass is see-through; a highlighted item must pop over it.
            if (clone.transparent && clone.opacity < 0.92) clone.opacity = 0.92;
            if (surface.emissive) {
              surface.emissive.copy(color);
              surface.color?.copy(color);
              surface.emissiveIntensity = GLOW_INTENSITY;
              (glows.get(owner!) ?? glows.set(owner!, []).get(owner!)!).push({ surface, base: GLOW_INTENSITY });
            } else surface.color?.copy(color);
          }
          clone.needsUpdate = true;
          return clone;
        };
        mesh.material = Array.isArray(mesh.material) ? mesh.material.map(modify) : modify(mesh.material);
        // Outline in the kind colour so doors and windows read at any zoom.
        const line = new LineSegments(new EdgesGeometry(mesh.geometry, 25), new LineBasicMaterial({ color: color.clone().multiplyScalar(0.7), depthTest: false, transparent: true }));
        line.raycast = () => {}; line.renderOrder = 10; line.userData.highlightOutline = true;
        mesh.add(line); outlines.push(line);
      });
    },
    clearHighlight,
    /** Scales an item's settled emissive glow (0 = unlit, 1 = settled, above 1 = pulse peak). */
    setGlow(id: string, factor: number): void {
      for (const entry of glows.get(id) ?? []) entry.surface.emissiveIntensity = entry.base * factor;
    },
    getHighlightState(): HighlightState {
      return { ...state, highlighted: [...state.highlighted], labels: { ...state.labels } };
    },
  };
}
