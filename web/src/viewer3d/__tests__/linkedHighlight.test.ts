// @vitest-environment node
import { describe, expect, it, vi } from 'vitest';
import { BoxGeometry, Color, Group, Mesh, MeshStandardMaterial } from 'three';
import type { GLTF } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { createScene, type SceneManifest } from '../scene';
import { createHighlightController } from '../highlight';
import { createLinkedHighlightController } from '../linkedHighlight';

function fixture() {
  const root = new Group();
  const material = new MeshStandardMaterial({ color: '#bf6333', opacity: 0.8, transparent: true });
  const a = new Mesh(new BoxGeometry(), material);
  const b = new Mesh(new BoxGeometry(), material);
  a.name = 'window-003'; b.name = 'door-001';
  root.add(a, b);
  const manifest: SceneManifest = {
    doc_id: 'generated-for-demo', glb: '', usdz: null, units: 'm', up: 'Y',
    origin_offset_m: [0, 0, 0], storeys: [],
    items: Object.fromEntries([a.name, b.name].map((id) => [id, {
      node: id, usd_name: `i_${id}`, kind: 'other', storey: null, bbox_m: null,
    }])),
  };
  const scene = createScene(manifest, {
    scene: root, parser: { associations: new Map(), json: {} } as unknown as GLTF['parser'],
  });
  return { scene, a, b, material, linked: createLinkedHighlightController(scene), answer: createHighlightController(scene) };
}

describe('local linked glow over answer highlights', () => {
  it('uses a soft hover and stronger selection, leaving other geometry unchanged', () => {
    const { a, b, material, linked } = fixture();
    linked.apply('window-003', null, new Color('#166ed1'));
    const hoverIntensity = a.material.emissiveIntensity;
    expect(hoverIntensity).toBeGreaterThan(0);
    expect(b.material).toBe(material);
    linked.apply('window-003', 'door-001', new Color('#166ed1'));
    expect(a.material.emissiveIntensity).toBe(hoverIntensity);
    expect(b.material.emissiveIntensity).toBeGreaterThan(hoverIntensity);
    linked.apply('window-003', 'window-003', new Color('#166ed1'));
    expect(a.material.emissiveIntensity).toBeGreaterThan(hoverIntensity);
    expect(b.material).toBe(material);
    linked.clear();
    expect(a.material).toBe(material);
  });

  it('reveals a dimmed item at its original opacity then restores the exact answer material and labels', () => {
    const { a, b, material, linked, answer } = fixture();
    answer.highlight(['door-001'], { labels: { 'door-001': '7' } });
    const answerMaterial = a.material;
    const otherMaterial = b.material;
    expect(answerMaterial.opacity).toBeLessThan(material.opacity);
    linked.apply(null, 'window-003', new Color('#166ed1'));
    expect(a.material.opacity).toBe(material.opacity);
    expect(a.material.color.equals(material.color)).toBe(true);
    expect(b.material).toBe(otherMaterial);
    const dispose = vi.spyOn(a.material, 'dispose');
    linked.clear();
    expect(dispose).toHaveBeenCalledOnce();
    expect(a.material).toBe(answerMaterial);
    expect(answer.getHighlightState()).toEqual({ highlighted: ['door-001'], dimmed: 1, labels: { 'door-001': '7' } });
    answer.clearHighlight();
    expect(a.material).toBe(material);
  });

  it('ignores unresolved IDs and disposes only its own materials on hover leave', () => {
    const { a, b, material, linked } = fixture();
    const disposeOriginal = vi.spyOn(material, 'dispose');
    linked.apply('missing', null, new Color('#166ed1'));
    expect(a.material).toBe(material);
    expect(b.material).toBe(material);
    linked.apply('window-003', null, new Color('#166ed1'));
    const disposeClone = vi.spyOn(a.material, 'dispose');
    linked.apply(null, null, new Color('#166ed1'));
    expect(disposeClone).toHaveBeenCalledOnce();
    expect(disposeOriginal).not.toHaveBeenCalled();
    expect(a.material).toBe(material);
    linked.clear();
    expect(disposeClone).toHaveBeenCalledOnce();
  });
});
