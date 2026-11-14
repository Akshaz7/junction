import { storeyName, type LoadedScene, type SceneManifest } from './scene';
import type { IFCElement } from './identify';

export interface CutawayState {
  activeStorey: string | null;
  showRoof: boolean;
  /** Resolved items hidden by the current visibility policy. */
  hiddenCount: number;
}

/** Elevations are taken from metadata; unknown elevations retain manifest order. */
export function cutawayStoreys(manifest: SceneManifest): { name: string; elevation_m?: number }[] {
  const entries = new Map<string, { name: string; elevation_m?: number }>();
  for (const storey of [...manifest.storeys, ...Object.values(manifest.items).map((item) => item.storey)]) {
    const name = storeyName(storey);
    if (name === null) continue;
    const elevation = typeof storey === 'object' && storey ? storey.elevation_m : undefined;
    const previous = entries.get(name);
    entries.set(name, { name, elevation_m: elevation ?? previous?.elevation_m });
  }
  return [...entries.values()].sort((a, b) => {
    if (a.elevation_m === undefined) return b.elevation_m === undefined ? 0 : 1;
    if (b.elevation_m === undefined) return -1;
    return a.elevation_m - b.elevation_m;
  });
}

export function isRoof(kind: string, element?: IFCElement): boolean {
  if (kind.toLowerCase() === 'roof' || element?.kind?.toLowerCase() === 'roof') return true;
  const ifcClass = element?.ifc_class?.toLowerCase();
  if (ifcClass === 'ifcroof') return true;
  if (ifcClass === 'ifcslab') return element?.predefined_type?.toUpperCase() === 'ROOF';
  return ifcClass === 'ifccovering' && /\broof(?:ing)?\b/i.test(
    `${element?.predefined_type ?? ''} ${element?.type_name ?? ''}`);
}

export function createCutawayController(scene: LoadedScene) {
  const storeys = cutawayStoreys(scene.manifest);
  const roofIds = new Set(Object.entries(scene.manifest.items)
    .filter(([id, item]) => isRoof(item.kind, scene.elements?.get(id))).map(([id]) => id));
  let activeStorey: string | null = storeys.find((storey) => storey.elevation_m !== undefined && storey.elevation_m >= 0)?.name
    ?? storeys[0]?.name ?? null;
  let showRoof = false;

  function apply(): void {
    for (const [object, visible] of scene.originalVisibility) object.visible = visible;
    const activeIndex = storeys.findIndex((storey) => storey.name === activeStorey);
    for (const [id, object] of scene.items) {
      const itemIndex = storeys.findIndex((storey) => storey.name === storeyName(scene.manifest.items[id].storey));
      // Explicitly showing the roof reveals it even above the cutaway plane.
      object.visible = scene.originalVisibility.get(object) !== false && (roofIds.has(id)
        ? showRoof : activeIndex < 0 || itemIndex <= activeIndex);
    }
    for (const object of scene.items.values()) {
      if (!object.visible) continue;
      for (let parent = object.parent; parent && parent !== scene.root; parent = parent.parent) {
        if (scene.originalVisibility.get(parent) !== false) parent.visible = true;
      }
    }
  }

  apply();
  return {
    storeys,
    hasRoof: roofIds.size > 0,
    setStorey(name: string | null) { activeStorey = name; apply(); },
    setShowRoof(value: boolean) { showRoof = value; apply(); },
    followHighlight(ids: readonly string[], cameraTargetItemId?: string) {
      const candidates = cameraTargetItemId ? [cameraTargetItemId, ...ids] : ids;
      const target = candidates.find((id) => scene.manifest.items[id]
        && storeyName(scene.manifest.items[id].storey) !== null);
      if (target) activeStorey = storeyName(scene.manifest.items[target].storey);
      // A roof answer must remain visible too.
      if (candidates.some((id) => roofIds.has(id))) showRoof = true;
      apply();
    },
    getState(): CutawayState {
      let hiddenCount = 0;
      for (const object of scene.items.values()) {
        for (let current: typeof object | null = object; current; current = current.parent) {
          if (!current.visible) { hiddenCount++; break; }
        }
      }
      return { activeStorey, showRoof, hiddenCount };
    },
  };
}
