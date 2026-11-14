// @vitest-environment node
import { describe, expect, it, vi } from 'vitest';
import { BoxGeometry, Color, Group, Mesh, MeshStandardMaterial, Texture } from 'three';
import type { GLTF } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { createHighlightController, itemBounds } from '../highlight';
import { createScene, setStorey, type SceneManifest } from '../scene';

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

  it('glows only selected IDs, dims/desaturates other items, and uses citation labels', () => {
    const { controller, material, a, b, c } = fixture();
    const originalColor = material.color.clone();
    const accent = new Color('#166ed1');
    controller.highlight(['window-a', 'wall-c'], { labels: { 'window-a': '7', 'wall-c': '12' } }, accent);
    expect(controller.getHighlightState()).toEqual({
      highlighted: ['window-a', 'wall-c'], dimmed: 1, labels: { 'window-a': '7', 'wall-c': '12' },
    });
    expect(a.material).not.toBe(material);
    expect(a.material.emissive.equals(accent)).toBe(true);
    expect(a.material.emissiveIntensity).toBeGreaterThan(1);
    expect(b.material.opacity).toBeLessThan(material.opacity);
    expect(b.material.transparent).toBe(true);
    expect(b.material.depthWrite).toBe(false);
    const saturation = (color: Color) => Math.max(color.r, color.g, color.b) - Math.min(color.r, color.g, color.b);
    expect(saturation(b.material.color)).toBeLessThan(saturation(originalColor));
    expect(b.material.emissive.getHex()).toBe(0);
    for (const cloned of c.material) {
      expect(cloned.emissive.equals(accent)).toBe(true);
      expect(cloned).not.toBe(a.material);
    }
    expect(material.color.equals(originalColor)).toBe(true);
    expect(material.opacity).toBe(0.8);
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
    expect(a.material.opacity).toBeLessThan(material.opacity);
    expect(b.material.emissiveIntensity).toBe(1.5);
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
    expect(b.material.emissiveIntensity).toBe(1.5);
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
