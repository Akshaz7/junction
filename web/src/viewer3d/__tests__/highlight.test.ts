// @vitest-environment node
import { describe, expect, it, vi } from 'vitest';
import { BoxGeometry, Color, Group, Mesh, MeshStandardMaterial, Texture } from 'three';
import type { GLTF } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { createHighlightController, HIGHLIGHT_AMBER, itemBounds } from '../highlight';
import { createScene, setStorey, type SceneManifest } from '../scene';
import { answerToVisualise } from '../visualise';
import { applyCommand, applyState, emptyCommandState, resolveCommandLabels, type SceneCommand } from '../commands';

function fixture() {
  const root = new Group();
  const material = new MeshStandardMaterial({ color: '#bf6333', opacity: 0.8, transparent: true, emissive: '#120608' });
  material.emissiveIntensity = 0.4;
  material.map = new Texture();
  const a = new Mesh(new BoxGeometry(2, 4, 2), material);
  a.name = 'window-a';
  const b = new Mesh(new BoxGeometry(), material);
  b.name = 'window-b';
  b.position.x = 5;
  const group = new Group();
  group.name = 'wall-c';
  const c = new Mesh(new BoxGeometry(), [material, material]);
  c.position.z = 6;
  group.add(c);
  root.add(a, b, group);
  const items = Object.fromEntries(['window-a', 'window-b', 'wall-c'].map((id) => [id, {
    node: id, usd_name: `i_${id}`, bbox_m: null, storey: id === 'window-a' ? 'Ground' : 'First', kind: 'window',
  }]));
  const manifest: SceneManifest = {
    doc_id: 'generated-for-demo', glb: '', usdz: null, units: 'm', up: 'Y',
    origin_offset_m: [0, 0, 0], storeys: ['Ground', 'First'], items,
  };
  const scene = createScene(manifest, {
    scene: root, parser: { associations: new Map(), json: {} } as unknown as GLTF['parser'],
  });
  return { scene, material, a, b, c, controller: createHighlightController(scene) };
}

describe('highlight materials and contract item state', () => {
  it('preserves answer citation labels and numeric defaults when scene items have tags', () => {
    const { scene, controller } = fixture();
    scene.manifest.items['window-a'].tag = 'W1';
    scene.manifest.items['window-b'].tag = 'W2';
    const evidence = answerToVisualise({
      doc_ids: [scene.manifest.doc_id],
      evidence: {
        scene: { doc_id: scene.manifest.doc_id, highlight_item_ids: ['window-b', 'window-a'] },
        boxes: [{ item_id: 'window-a', label: '7' }, { item_id: 'window-b', label: '12' }],
      },
    });
    controller.highlight(evidence.highlight, { labels: evidence.labels });
    expect(controller.getHighlightState().labels).toEqual({ 'window-b': '12', 'window-a': '7' });
    controller.highlight(evidence.highlight);
    expect(controller.getHighlightState().labels).toEqual({ 'window-b': '1', 'window-a': '2' });
    controller.clearHighlight();
  });

  it.each(['highlight', 'isolate'] as const)('uses tags for %s commands, preserving explicit labels and untagged IDs', (op) => {
    const { scene, controller } = fixture();
    scene.manifest.items['window-a'].tag = 'W1';
    scene.manifest.items['window-b'].tag = 'W2';
    const command: SceneCommand = { op, item_ids: ['window-b', 'wall-c', 'window-a'], labels: { 'window-a': 'Opening W1' } };
    const labels = resolveCommandLabels(command.item_ids, command.labels, scene.manifest.items);
    const state = applyCommand(emptyCommandState(), { ...command, labels });
    controller.highlight([...state.highlighted.keys()], { labels: Object.fromEntries(state.highlighted) });
    expect(controller.getHighlightState().labels).toEqual({ 'window-b': 'W2', 'wall-c': 'wall-c', 'window-a': 'Opening W1' });
    expect(command.labels).toEqual({ 'window-a': 'Opening W1' });
    controller.clearHighlight();
  });

  it('resolves omitted snapshot labels from tags without replacing supplied labels', () => {
    const { scene, controller } = fixture();
    scene.manifest.items['window-a'].tag = 'W1';
    scene.manifest.items['window-b'].tag = 'W2';
    const snapshot = { hidden: [], highlighted: ['window-b', 'window-a'], labels: { 'window-a': 'Selected W1' } };
    const state = applyState({ ...snapshot,
      labels: resolveCommandLabels(snapshot.highlighted, snapshot.labels, scene.manifest.items) });
    controller.highlight([...state.highlighted.keys()], { labels: Object.fromEntries(state.highlighted) });
    expect(controller.getHighlightState().labels).toEqual({ 'window-b': 'W2', 'window-a': 'Selected W1' });
    controller.clearHighlight();
  });

  it('preserves the textured plan floor while the answer items glow', () => {
    const { scene, controller } = fixture();
    const floor = new Mesh(new BoxGeometry(), new MeshStandardMaterial());
    floor.name = 'plan_floor';
    floor.material.map = new Texture();
    scene.root.add(floor);
    const original = floor.material;
    controller.highlight(['window-a']);
    expect(floor.material).toBe(original);
    expect(floor.material.opacity).toBe(1);
    controller.clearHighlight();
    expect(floor.material).toBe(original);
  });

  it('keeps citation numbers tied to IDs when selection order differs from scene order', () => {
    const { controller } = fixture();
    const ids = ['wall-c', 'window-b', 'window-a'];
    controller.highlight(ids);
    expect(controller.getHighlightState()).toEqual({
      highlighted: ids, dimmed: 0,
      labels: { 'wall-c': '1', 'window-b': '2', 'window-a': '3' },
    });
    // Supplied 2D evidence labels take precedence over selection position.
    controller.highlight(ids, { labels: { 'window-a': '7', 'window-b': '12', 'wall-c': '4' } });
    expect(controller.getHighlightState().labels).toEqual({
      'wall-c': '4', 'window-b': '12', 'window-a': '7',
    });
    controller.clearHighlight();
  });

  it('glows amber on selected IDs and preserves exact surrounding materials and textures', () => {
    const { controller, material, a, b, c } = fixture();
    const originalColor = material.color.clone();
    const accent = new Color(HIGHLIGHT_AMBER);
    controller.highlight(['window-a', 'wall-c'], { labels: { 'window-a': '7', 'wall-c': '12' } });
    expect(controller.getHighlightState()).toEqual({
      highlighted: ['window-a', 'wall-c'], dimmed: 1, labels: { 'window-a': '7', 'wall-c': '12' },
    });
    expect(a.material).not.toBe(material);
    expect(a.material.emissive.equals(accent)).toBe(true);
    expect(a.material.emissiveIntensity).toBeGreaterThan(1);
    expect(b.material).toBe(material);
    expect(b.material.map).toBe(material.map);
    expect(b.material.color.equals(originalColor)).toBe(true);
    expect(b.material.opacity).toBe(0.8);
    expect(b.material.emissive.getHex()).toBe(material.emissive.getHex());
    for (const cloned of c.material) {
      expect(cloned.emissive.equals(accent)).toBe(true);
      expect(cloned).not.toBe(a.material);
    }
    expect(material.color.equals(originalColor)).toBe(true);
    expect(material.opacity).toBe(0.8);
    controller.clearHighlight();
  });

  it('accepts a per-id accent so each kind glows in its own colour', () => {
    const { controller, a, c } = fixture();
    const window = new Color('#0072B2');
    const wall = new Color('#E69F00');
    controller.highlight(['window-a', 'wall-c'], {}, (id) => (id.startsWith('window') ? window : wall));
    expect(a.material.emissive.equals(window)).toBe(true);
    for (const cloned of c.material) expect(cloned.emissive.equals(wall)).toBe(true);
    controller.clearHighlight();
  });

  it('clear restores exact shared materials and arrays, disposing only clones', () => {
    const { controller, material, a, b, c } = fixture();
    const originalArray = c.material;
    const originalJson = material.toJSON();
    const disposeOriginal = vi.spyOn(material, 'dispose');
    const disposeTexture = vi.spyOn(material.map!, 'dispose');
    controller.highlight(['window-a']);
    const disposeClone = vi.spyOn(a.material, 'dispose');
    controller.clearHighlight();
    expect(a.material).toBe(material);
    expect(b.material).toBe(material);
    expect(c.material).toBe(originalArray);
    expect(material.toJSON()).toEqual(originalJson);
    expect(disposeClone).toHaveBeenCalledOnce();
    expect(disposeOriginal).not.toHaveBeenCalled();
    expect(disposeTexture).not.toHaveBeenCalled();
    expect(controller.getHighlightState()).toEqual({ highlighted: [], dimmed: 0, labels: {} });
    controller.clearHighlight();
    expect(disposeClone).toHaveBeenCalledOnce();
  });

  it('replaces selections, ignores unresolved IDs, deduplicates, and clears on an empty selection', () => {
    const { controller, material, a, b } = fixture();
    controller.highlight(['window-a', 'missing', 'window-a']);
    expect(controller.getHighlightState()).toEqual({ highlighted: ['window-a'], dimmed: 2, labels: { 'window-a': '1' } });
    const disposeClone = vi.spyOn(a.material, 'dispose');
    controller.highlight(['window-b']);
    expect(disposeClone).toHaveBeenCalledOnce();
    expect(a.material).toBe(material);
    expect(b.material.emissiveIntensity).toBe(2.8);
    expect(controller.getHighlightState().highlighted).toEqual(['window-b']);
    const snapshot = controller.getHighlightState();
    snapshot.highlighted.push('fake');
    snapshot.labels['window-b'] = 'fake';
    expect(controller.getHighlightState().labels['window-b']).toBe('1');
    expect(controller.getHighlightState().highlighted).toEqual(['window-b']);
    controller.highlight(['missing']);
    expect(a.material).toBe(material);
    expect(controller.getHighlightState().dimmed).toBe(0);
  });

  it('keeps storey visibility while applying and clearing highlights', () => {
    const { scene, controller, b } = fixture();
    setStorey(scene, 'Ground');
    expect(b.visible).toBe(false);
    controller.highlight(['window-b']);
    expect(b.material.emissiveIntensity).toBe(2.8);
    expect(b.visible).toBe(false);
    controller.clearHighlight();
    expect(b.visible).toBe(false);
    setStorey(scene, null);
    expect(b.visible).toBe(true);
  });

  it('fits transformed geometry and unions multiple selected item bounds', () => {
    const { scene } = fixture();
    scene.root.position.set(10, 2, -5);
    const bounds = itemBounds(scene, ['window-a']);
    expect(bounds.min.toArray()).toEqual([9, 0, -6]);
    expect(bounds.max.toArray()).toEqual([11, 4, -4]);
    const union = itemBounds(scene, ['window-a', 'window-b']);
    expect(union.max.x).toBe(15.5);
    expect(itemBounds(scene, ['missing']).isEmpty()).toBe(true);
  });
});
