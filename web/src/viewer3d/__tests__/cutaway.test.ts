// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { Group } from 'three';
import { createScene, itemIdForObject, type SceneManifest } from '../scene';
import { createCutawayController, isRoof } from '../cutaway';
import { createHighlightController } from '../highlight';

function fixture() {
  const manifest: SceneManifest = {
    doc_id: 'generated-for-demo', glb: 'scene.glb', usdz: null, units: 'm', up: 'Y', origin_offset_m: [0, 0, 0],
    storeys: [{ name: 'Upper', elevation_m: 3 }, { name: 'Basement', elevation_m: -3 }, { name: 'Ground', elevation_m: 0 }],
    items: Object.fromEntries([
      ['basement', 'wall', 'Basement'], ['ground', 'window', 'Ground'], ['upper', 'window', 'Upper'],
      ['roof', 'roof', 'Upper'], ['slab-roof', 'slab', 'Upper'], ['covering-roof', 'other', 'Upper'],
      ['floor-slab', 'slab', 'Ground'], ['site', 'site', null],
    ].map(([id, kind, storey]) => [id!, { node: id!, usd_name: id!, bbox_m: null, storey, kind: kind! }])),
  };
  const root = new Group();
  for (const id of Object.keys(manifest.items)) { const object = new Group(); object.name = id; root.add(object); }
  const scene = createScene(manifest, { scene: root, parser: { associations: new Map(), json: {} } } as Parameters<typeof createScene>[1]);
  scene.elements = new Map([
    ['slab-roof', { item_id: 'slab-roof', ifc_class: 'IfcSlab', predefined_type: 'ROOF' }],
    ['covering-roof', { item_id: 'covering-roof', ifc_class: 'IfcCovering', type_name: 'Roof membrane' }],
    ['floor-slab', { item_id: 'floor-slab', ifc_class: 'IfcSlab', predefined_type: 'FLOOR' }],
  ]);
  return scene;
}
const visible = (scene: ReturnType<typeof fixture>, id: string) => itemIdForObject(scene, scene.items.get(id)!) !== null;

describe('cutaway policy (generated for demo fixture)', () => {
  it('defaults to ground, hiding all roof classifications and upper storeys', () => {
    const scene = fixture();
    const cutaway = createCutawayController(scene);
    expect(cutaway.getState()).toEqual({ activeStorey: 'Ground', showRoof: false, hiddenCount: 4 });
    expect(cutaway.hasRoof).toBe(true);
    for (const id of ['basement', 'ground', 'floor-slab', 'site']) expect(visible(scene, id), id).toBe(true);
    for (const id of ['upper', 'roof', 'slab-roof', 'covering-roof']) expect(visible(scene, id), id).toBe(false);
  });
  it('reveals roof geometry above the cut, preserving the cut for other upper items', () => {
    const scene = fixture();
    const cutaway = createCutawayController(scene);
    cutaway.setShowRoof(true);
    expect(cutaway.getState().hiddenCount).toBe(1);
    for (const id of ['roof', 'slab-roof', 'covering-roof']) expect(visible(scene, id)).toBe(true);
    expect(visible(scene, 'upper')).toBe(false);
    cutaway.setShowRoof(false);
    expect(cutaway.getState().hiddenCount).toBe(4);
  });
  it('steps in elevation order while retaining lower storeys; all-storeys remains available', () => {
    const cutaway = createCutawayController(fixture());
    expect(cutaway.storeys.map((storey) => storey.name)).toEqual(['Basement', 'Ground', 'Upper']);
    cutaway.setStorey('Basement');
    expect(cutaway.getState().hiddenCount).toBe(6);
    cutaway.setStorey('Upper');
    expect(cutaway.getState().hiddenCount).toBe(3);
    cutaway.setStorey(null);
    expect(cutaway.getState()).toEqual({ activeStorey: null, showRoof: false, hiddenCount: 3 });
  });
  it('follows the camera target or first valid highlight and preserves numbered highlights', () => {
    const scene = fixture();
    const cutaway = createCutawayController(scene);
    const highlight = createHighlightController(scene);
    cutaway.followHighlight(['upper']);
    highlight.highlight(['upper'], { labels: { upper: '12' } });
    expect(cutaway.getState().activeStorey).toBe('Upper');
    expect(visible(scene, 'upper')).toBe(true);
    expect(highlight.getHighlightState().labels).toEqual({ upper: '12' });
    cutaway.followHighlight(['upper', 'ground'], 'ground'); // spans storeys: keep both, cut above the highest
    expect(cutaway.getState().activeStorey).toBe('Upper');
    cutaway.followHighlight(['ground'], 'ground');
    expect(cutaway.getState().activeStorey).toBe('Ground');
    cutaway.followHighlight(['missing', 'basement']);
    expect(cutaway.getState().activeStorey).toBe('Basement');
    cutaway.followHighlight([]);
    highlight.clearHighlight();
    expect(cutaway.getState().activeStorey).toBe('Basement');
    expect(visible(scene, 'upper')).toBe(false);
  });
  it('reveals a roof answer without resurrecting originally hidden objects', () => {
    const scene = fixture();
    scene.originalVisibility.set(scene.items.get('ground')!, false);
    const cutaway = createCutawayController(scene);
    cutaway.followHighlight(['slab-roof']);
    expect(cutaway.getState()).toMatchObject({ activeStorey: 'Upper', showRoof: true });
    expect(visible(scene, 'slab-roof')).toBe(true);
    expect(visible(scene, 'ground')).toBe(false);
  });
  it('leaves roofless single-storey extrusions unchanged', () => {
    const scene = fixture();
    scene.manifest.storeys = [{ name: 'Ground', elevation_m: 0 }];
    for (const [id, object] of [...scene.items]) {
      if (id === 'ground') continue;
      object.removeFromParent(); scene.items.delete(id); delete scene.manifest.items[id];
    }
    const cutaway = createCutawayController(scene);
    expect(cutaway.hasRoof).toBe(false);
    expect(cutaway.getState()).toEqual({ activeStorey: 'Ground', showRoof: false, hiddenCount: 0 });
    expect(visible(scene, 'ground')).toBe(true);
  });
  it('does not classify ordinary slabs or ceilings as roofs', () => {
    expect(isRoof('slab', { item_id: 'floor', ifc_class: 'IfcSlab', predefined_type: 'FLOOR', type_name: 'Roof access floor' })).toBe(false);
    expect(isRoof('other', { item_id: 'ceiling', ifc_class: 'IfcCovering', predefined_type: 'CEILING' })).toBe(false);
    expect(isRoof('other', { item_id: 'roof', ifc_class: 'IfcCovering', predefined_type: 'ROOFING' })).toBe(true);
  });
  it('prefers the lowest known nonnegative elevation even with unknown storeys in the manifest', () => {
    const scene = fixture();
    scene.manifest.storeys = [{ name: 'Upper', elevation_m: 3 }, 'Unknown', { name: 'Ground', elevation_m: 0 }];
    expect(createCutawayController(scene).getState().activeStorey).toBe('Ground');
  });
});
