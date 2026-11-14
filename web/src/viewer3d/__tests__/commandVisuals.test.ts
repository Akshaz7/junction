import { BoxGeometry, Group, Mesh, MeshStandardMaterial } from 'three';
import { describe, expect, it } from 'vitest';
import { createCommandVisuals } from '../commandVisuals';
import { applyCommand, emptyCommandState } from '../commands';
import { createScene, disposeScene, type SceneManifest } from '../scene';

function fixture() {
  const root = new Group();
  const source = new MeshStandardMaterial({ opacity: 0.8 });
  const a = new Mesh(new BoxGeometry(), source); a.name = 'a';
  const b = new Group(); b.name = 'b';
  const child = new Mesh(new BoxGeometry(), source); b.add(child); root.add(a, b);
  const item = (node: string) => ({ node, usd_name: node, kind: 'window', storey: null, bbox_m: null });
  const scene = createScene({ items: { a: item('a'), b: item('b') } } as unknown as SceneManifest,
    { scene: root, parser: { associations: new Map(), json: {} } } as Parameters<typeof createScene>[1]);
  return { scene, a, b, child, source, visuals: createCommandVisuals(scene) };
}

describe('scene edit visibility/material layer', () => {
  it('fades for 250 ms, disables after fade, and reverses an interrupted hide', () => {
    const { scene, a, b, source, visuals } = fixture();
    const hidden = applyCommand(emptyCommandState(), { op: 'hide', item_ids: ['a'] });
    visuals.setState(hidden, 0, false);
    visuals.sample(125);
    expect(a.visible).toBe(true);
    expect(a.material.opacity).toBeCloseTo(0.4);
    visuals.setState(emptyCommandState(), 125, false);
    visuals.sample(250);
    expect(a.material.opacity).toBeCloseTo(0.6);
    visuals.sample(375);
    expect(a.visible).toBe(true); expect(a.material.opacity).toBeCloseTo(0.8);
    visuals.setState(hidden, 400, false); visuals.sample(650);
    expect(a.visible).toBe(false); expect(b.visible).toBe(true);
    visuals.setState(emptyCommandState(), 650, false); visuals.sample(900);
    expect(a.visible).toBe(true);
    expect(source.opacity).toBe(0.8);
    visuals.dispose(); expect(a.material).toBe(source); disposeScene(scene);
  });

  it('reduced motion is immediate and storey visibility wins over restore', () => {
    const { scene, a, visuals } = fixture();
    const hidden = applyCommand(emptyCommandState(), { op: 'hide', item_ids: ['a'] });
    visuals.setState(hidden, 0, true); expect(a.visible).toBe(false);
    visuals.setState(emptyCommandState(), 0, true); expect(a.visible).toBe(true);
    a.visible = false; visuals.captureVisibility();
    visuals.setState(hidden, 0, false);
    visuals.setState(emptyCommandState(), 100, false); visuals.sample(350);
    expect(a.visible).toBe(false);
    visuals.dispose(); disposeScene(scene);
  });

  it('isolation dims nested meshes without hiding them and reset restores shared source materials', () => {
    const { scene, a, b, child, source, visuals } = fixture();
    visuals.setState(applyCommand(emptyCommandState(), { op: 'isolate', item_ids: ['a'] }), 0, true);
    expect(a.material).toBe(source); expect(child.material.opacity).toBeCloseTo(0.8 * 0.18);
    expect(b.visible).toBe(true); expect(source.opacity).toBe(0.8);
    visuals.setState(emptyCommandState(), 10, true);
    expect(child.material).toBe(source);
    visuals.dispose(); disposeScene(scene);
  });
});
