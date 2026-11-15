import { useCallback, useRef, useEffect, useMemo, useState, type CSSProperties, type JSX } from 'react';
import { Button } from '../components/ui';
import { itemKindKey, kindStyle, type KindKey } from '../lib/kind-colors';
import type { LoadedScene } from './scene';
import type { Viewer } from './viewer';
import '../components/viewer-tools/plan-layers.css';

/** 3D layers: the 2D plan layers (walls/doors/windows/rooms/fixtures) plus the IFC kinds a plan map has no layer for. */
export type Layer3DKey = 'wall' | 'door' | 'window' | 'floor' | 'stairs' | 'structure' | 'fixture' | 'pipe' | 'duct' | 'other';
export const LAYER3D_KEYS: readonly Layer3DKey[] = ['wall', 'door', 'window', 'floor', 'stairs', 'structure', 'fixture', 'pipe', 'duct', 'other'];
const LABELS: Record<Layer3DKey, string> = {
  wall: 'Walls', door: 'Doors', window: 'Windows', floor: 'Rooms/Floors', stairs: 'Stairs',
  structure: 'Structure', fixture: 'Fixtures', pipe: 'Pipes', duct: 'Ducts', other: 'Other',
};
/** Chip swatch colour per layer (same palette as the 2D chips and the 3D highlights). */
const COLOR_KIND: Record<Layer3DKey, KindKey> = {
  wall: 'wall', door: 'door', window: 'window', floor: 'room', stairs: 'stairs',
  structure: 'column', fixture: 'toilet', pipe: 'pipe', duct: 'fitting', other: 'other',
};
const BY_KIND: Partial<Record<KindKey, Layer3DKey>> = {
  wall: 'wall', door: 'door', window: 'window', room: 'floor', slab: 'floor', stairs: 'stairs',
  column: 'structure', beam: 'structure', member: 'structure',
  toilet: 'fixture', sink: 'fixture', shower: 'fixture', bathtub: 'fixture',
  pipe: 'pipe', drain: 'pipe', fitting: 'pipe',
};

/** Ventilation kinds (ifc_scene: IfcDuctSegment/IfcDuctFitting/IfcAirTerminal); no 2D colour key, so matched by name. */
const DUCT_KINDS = new Set(['duct', 'duct_fitting', 'duct_segment', 'air_terminal', 'terminal', 'damper']);

export function layer3dOf(item: Parameters<typeof itemKindKey>[0]): Layer3DKey {
  if (item && DUCT_KINDS.has((item.kind ?? '').toLowerCase())) return 'duct';
  return BY_KIND[itemKindKey(item)] ?? 'other';
}

/** Item ids per layer, from the scene manifest. */
export function groupSceneItems(scene: Pick<LoadedScene, 'manifest'> | null): Map<Layer3DKey, string[]> {
  const groups = new Map<Layer3DKey, string[]>(LAYER3D_KEYS.map((k) => [k, []]));
  if (scene) for (const [id, item] of Object.entries(scene.manifest.items)) groups.get(layer3dOf(item))!.push(id);
  return groups;
}

/**
 * Purely visual hide set (not a scene command: no Undo entry, no chat broadcast, not saved).
 * Added to viewer.ts by the lead; until then the chips render but do nothing.
 */
type LayerViewer = Viewer & { setLayerHidden?(item_ids: readonly string[]): void };

/** Toggle chips with counts; all layers on by default. Layers with no items are not shown. */
export function Layers3D({ viewer }: { viewer: Viewer | null }): JSX.Element | null {
  const [scene, setScene] = useState<LoadedScene | null>(() => viewer?.scene ?? null);
  const [off, setOff] = useState<ReadonlySet<Layer3DKey>>(() => new Set());

  // A scene swap runs the cutaway notify, so this also catches loadScene/setScene.
  useEffect(() => {
    if (!viewer) { setScene(null); return; }
    setScene(viewer.scene);
    return viewer.onCutawayChange(() => setScene(viewer.scene));
  }, [viewer]);

  const groups = useMemo(() => groupSceneItems(scene), [scene]);

  // Only touch the viewer when something is (or was) hidden: an all-on layer set must not reset the cutaway/build state.
  const applied = useRef(0);
  useEffect(() => {
    if (!viewer || !scene) return;
    const ids = [...off].flatMap((key) => groups.get(key) ?? []);
    if (!ids.length && !applied.current) return;
    applied.current = ids.length;
    (viewer as LayerViewer).setLayerHidden?.(ids);
  }, [viewer, scene, groups, off]);

  const toggle = useCallback((key: Layer3DKey) => setOff((prev) => {
    const next = new Set(prev);
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  }), []);

  const keys = LAYER3D_KEYS.filter((k) => groups.get(k)!.length > 0);
  if (!viewer || !keys.length) return null;
  return (
    <div className="plan-layer-chips layers3d-chips" role="group" aria-label="3D layers">
      {keys.map((key) => {
        const count = groups.get(key)!.length;
        const on = !off.has(key);
        return (
          <Button key={key} variant="ghost" size="xs" className={`plan-layer-chip ${on ? 'is-on' : ''}`} aria-pressed={on} data-layer={key}
            aria-label={`${on ? 'Hide' : 'Show'} ${LABELS[key].toLowerCase()} (${count})`}
            style={{ '--kind-color': kindStyle(COLOR_KIND[key]).color } as CSSProperties}
            onClick={() => toggle(key)}>
            <span className="plan-layer-swatch" aria-hidden="true" />{LABELS[key]} {count}
          </Button>
        );
      })}
    </div>
  );
}
