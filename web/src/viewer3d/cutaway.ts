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

/** Building-services kinds (ifc_scene MEP classes): shown as their own layer next to the building. */
const SERVICE_KINDS = new Set(['duct', 'duct_fitting', 'terminal', 'air_terminal', 'valve_damper', 'pump_fan', 'pipe', 'pipe_fitting',
  'equipment', 'mep_other', 'cable_tray', 'cable', 'valve', 'damper', 'fan', 'pump', 'tank', 'light']);
const AIR_KINDS = new Set(['duct', 'duct_fitting', 'terminal', 'air_terminal', 'valve_damper', 'damper', 'fan', 'pump_fan']);

export type ModelLayer = 'all' | 'building' | 'services';

export function isService(kind: string | undefined | null): boolean {
  return SERVICE_KINDS.has((kind ?? '').toLowerCase());
}

/** Null when the scene lacks either building or services items (no layer choice to offer). */
export function serviceLayerLabel(manifest: Pick<SceneManifest, 'items'>): string | null {
  const kinds = Object.values(manifest.items).map((item) => (item.kind ?? '').toLowerCase());
  const services = kinds.filter((kind) => SERVICE_KINDS.has(kind));
  if (!services.length || services.length === kinds.length) return null;
  return services.every((kind) => AIR_KINDS.has(kind)) ? 'Ventilation' : 'Services';
}

export function createCutawayController(scene: LoadedScene) {
  const storeys = cutawayStoreys(scene.manifest);
  const roofIds = new Set(Object.entries(scene.manifest.items)
    .filter(([id, item]) => isRoof(item.kind, scene.elements?.get(id))).map(([id]) => id));
  let activeStorey: string | null = storeys.find((storey) => storey.elevation_m !== undefined && storey.elevation_m >= 0)?.name
    ?? storeys[0]?.name ?? null;
  let showRoof = false;
  let layer: ModelLayer = 'all';
  const layerShows = (id: string) => layer === 'all' || (isService(scene.manifest.items[id]?.kind) === (layer === 'services'));

  function apply(): void {
    for (const [object, visible] of scene.originalVisibility) object.visible = visible;
    const activeIndex = storeys.findIndex((storey) => storey.name === activeStorey);
    for (const [id, object] of scene.items) {
      const itemIndex = storeys.findIndex((storey) => storey.name === storeyName(scene.manifest.items[id].storey));
      // Explicitly showing the roof reveals it even above the cutaway plane.
      object.visible = scene.originalVisibility.get(object) !== false && (roofIds.has(id)
        ? showRoof : activeIndex < 0 || itemIndex <= activeIndex) && layerShows(id);
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
    setLayer(value: ModelLayer) { layer = value; apply(); },
    getLayer(): ModelLayer { return layer; },
    followHighlight(ids: readonly string[], cameraTargetItemId?: string) {
      const candidates = cameraTargetItemId ? [cameraTargetItemId, ...ids] : ids;
      // An answer spanning several storeys keeps all of them (cut only above the highest one); roof stays off.
      let top = -1;
      for (const id of candidates) {
        const name = scene.manifest.items[id] ? storeyName(scene.manifest.items[id].storey) : null;
        if (name !== null) top = Math.max(top, storeys.findIndex((storey) => storey.name === name));
      }
      if (top >= 0) activeStorey = storeys[top].name;
      // A roof answer must remain visible too.
      if (candidates.some((id) => roofIds.has(id))) showRoof = true;
      // An answer about an item the layer filter hides brings both layers back.
      if (candidates.some((id) => scene.manifest.items[id] && !layerShows(id))) layer = 'all';
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
