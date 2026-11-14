// @vitest-environment node
import { describe, expect, it, vi } from 'vitest';
import { Group, Object3D } from 'three';
import type { GLTF } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { createScene, type SceneManifest } from '../scene';
import { buildSteps, createBuildAnimation, FLAT_DURATION_MS, isIfcManifest, scheduleBuildTransitions, stepDurationMs } from '../rise';
import { answerToVisualise, type VisualiseAnswer } from '../visualise';

type Spec = { kind: string; storey?: string | null; bbox?: [[number, number, number], [number, number, number]] };

function sceneOf(items: Record<string, Spec>, storeys: SceneManifest['storeys'] = []) {
  const root = new Group();
  const nodes = new Map<string, Object3D>();
  for (const [id] of Object.entries(items)) {
    const node = new Object3D();
    node.name = id;
    node.scale.y = 3;
    node.position.y = 1;
    root.add(node);
    nodes.set(id, node);
  }
  const manifest: SceneManifest = {
    doc_id: 'generated-for-demo', glb: '', usdz: null, units: 'm', up: 'Y', origin_offset_m: [0, 0, 0], storeys,
    items: Object.fromEntries(Object.entries(items).map(([id, item]) => [id, {
      node: id, kind: item.kind, usd_name: id, storey: item.storey ?? null, bbox_m: item.bbox ?? null,
    }])),
  };
  const scene = createScene(manifest, { scene: root, parser: { associations: new Map(), json: {} } as unknown as GLTF['parser'] });
  return { scene, nodes, manifest };
}

const IFC = {
  f1: { kind: 'footing', storey: 'Ground' },
  s0: { kind: 'slab', storey: 'Ground' }, w0: { kind: 'wall', storey: 'Ground' }, d0: { kind: 'door', storey: 'Ground' },
  st0: { kind: 'stairs', storey: 'Ground' }, c0: { kind: 'column', storey: 'Ground' },
  s1: { kind: 'slab', storey: 'First' }, w1: { kind: 'wall', storey: 'First' }, win1: { kind: 'window', storey: 'First' },
  r: { kind: 'roof', storey: 'First' }, site: { kind: 'site', storey: null },
};
const IFC_STOREYS = [{ name: 'First', elevation_m: 3 }, { name: 'Ground', elevation_m: 0 }];

describe('build steps', () => {
  it('orders IFC as foundations, per storey slab/structure/walls/stairs/openings (lowest first), then roof', () => {
    const { manifest } = sceneOf(IFC, IFC_STOREYS);
    expect(isIfcManifest(manifest)).toBe(true);
    expect(buildSteps(manifest).map((step) => step.label)).toEqual([
      'Foundations', 'Ground slab', 'Ground columns and beams', 'Ground walls', 'Ground stairs', 'Ground doors and windows',
      'First slab', 'First walls', 'First doors and windows', 'Roof',
    ]);
    expect(buildSteps(manifest).flatMap((step) => step.ids)).not.toContain('site');
  });

  it('gives raster and DXF plans floor, walls, then doors and windows', () => {
    const { manifest } = sceneOf({
      'room-001': { kind: 'room' }, 'wall-001': { kind: 'wall' }, 'door-001': { kind: 'door' },
      'window-001': { kind: 'window' }, 'sink-001': { kind: 'sink' },
    });
    expect(isIfcManifest(manifest)).toBe(false);
    expect(buildSteps(manifest)).toEqual([
      { label: 'Floor', ids: ['room-001'] }, { label: 'Walls', ids: ['wall-001'] },
      { label: 'Doors and windows', ids: ['door-001', 'window-001', 'sink-001'] },
    ]);
  });

  it('keeps the whole show around 7 s and each step between 200 and 600 ms', () => {
    expect(stepDurationMs(12)).toBeCloseTo(583.3, 0);
    expect(stepDurationMs(100)).toBe(200);
    expect(stepDurationMs(3)).toBe(600);
  });
});

describe('staged build-up animation', () => {
  const plan = {
    'room-001': { kind: 'room', bbox: [[0, 0, 0], [1, 0.1, 1]] as [[number, number, number], [number, number, number]] },
    'wall-001': { kind: 'wall', bbox: [[0, 0, 0], [1, 3, 1]] as [[number, number, number], [number, number, number]] },
    'door-001': { kind: 'door', bbox: [[0, 0, 0], [1, 2, 1]] as [[number, number, number], [number, number, number]] },
  };

  it('scrubs continuously within a step, reusing the same nodes and exact base transforms', () => {
    const { scene, nodes } = sceneOf(plan);
    const wall = nodes.get('wall-001')!;
    const animation = createBuildAnimation(scene, 0);
    animation.setPosition(1.25); animation.sample(100);
    const quarter = wall.scale.y;
    expect(quarter).toBeGreaterThan(0); expect(quarter).toBeLessThan(3);
    animation.setPosition(1.75); animation.sample(100);
    expect(nodes.get('wall-001')).toBe(wall);
    expect(wall.scale.y).toBeGreaterThan(quarter); expect(wall.scale.y).toBeLessThan(3);
    animation.setPosition(1.25); animation.sample(100);
    expect(wall.scale.y).toBe(quarter);
    animation.setPosition(0); expect(animation.sample(100).progress).toBe(0);
    animation.setPosition(3); expect(animation.sample(100).phase).toBe('done');
    expect(wall.scale.y).toBe(3); expect(wall.position.y).toBe(1);
  });

  it('holds the flat plan, then grows step by step and restores exact transforms when done', () => {
    const { scene, nodes } = sceneOf(plan);
    const start = 100;
    const animation = createBuildAnimation(scene, start);
    const step = animation.stepMs;
    expect(animation.sample(start)).toMatchObject({ index: 1, total: 3, phase: 'flat', playing: true, label: 'Floor' });
    expect([...nodes.values()].map((node) => node.scale.y)).toEqual([0, 0, 0]);
    // Half way through step 1: the room has grown, the wall has not started.
    const half = animation.sample(start + FLAT_DURATION_MS + step / 2);
    expect(half).toMatchObject({ index: 1, phase: 'rising' });
    expect(nodes.get('room-001')!.scale.y).toBeGreaterThan(0);
    expect(nodes.get('room-001')!.scale.y).toBeLessThan(3);
    expect(nodes.get('wall-001')!.scale.y).toBe(0);
    // Growth is anchored at the item's own base (world y 0 → position 0 while collapsed).
    expect(nodes.get('wall-001')!.position.y).toBe(0);
    const third = animation.sample(start + FLAT_DURATION_MS + step * 2.5);
    expect(third).toMatchObject({ index: 3, phase: 'rising', label: 'Doors and windows' });
    expect(nodes.get('room-001')!.scale.y).toBe(3);
    expect(nodes.get('wall-001')!.scale.y).toBe(3);
    const done = animation.sample(start + FLAT_DURATION_MS + step * 3 + 1);
    expect(done).toMatchObject({ index: 3, phase: 'done', playing: false, progress: 1 });
    for (const node of nodes.values()) { expect(node.scale.y).toBe(3); expect(node.position.y).toBe(1); }
  });

  it('scrubs both ways, pauses, and steps; the camera is never involved', () => {
    const { scene, nodes } = sceneOf(plan);
    const animation = createBuildAnimation(scene, 0);
    animation.setStep(2);
    expect(animation.sample(10_000)).toMatchObject({ index: 2, playing: false, phase: 'rising', label: 'Walls' });
    expect(nodes.get('wall-001')!.scale.y).toBe(3);
    expect(nodes.get('door-001')!.scale.y).toBe(0);
    animation.setStep(1);
    expect(animation.sample(20_000).index).toBe(1);
    expect(nodes.get('wall-001')!.scale.y).toBe(0);
    animation.setStep(3);
    expect(animation.sample(20_000).phase).toBe('done');
    // Play from the end restarts from the plan; pause rounds up to the step on screen.
    animation.play(30_000);
    expect(animation.sample(30_000).index).toBe(1);
    animation.pause(30_000 + animation.stepMs * 1.2);
    expect(animation.sample(60_000)).toMatchObject({ index: 2, playing: false });
  });

  it('keeps pinned (answer highlight) items fully visible at every step', () => {
    const { scene, nodes } = sceneOf(plan);
    const animation = createBuildAnimation(scene, 0, { pinned: () => ['door-001'] });
    animation.setStep(1);
    animation.sample(5);
    expect(nodes.get('door-001')!.scale.y).toBe(3);
    expect(nodes.get('door-001')!.position.y).toBe(1);
    expect(nodes.get('wall-001')!.scale.y).toBe(0);
  });

  it('reduced motion shows the finished model at once but the slider still works', () => {
    const { scene, nodes } = sceneOf(plan);
    const animation = createBuildAnimation(scene, 0, { reducedMotion: true });
    expect(animation.sample(0)).toMatchObject({ phase: 'done', playing: false, index: 3, progress: 1 });
    expect([...nodes.values()].map((node) => node.scale.y)).toEqual([3, 3, 3]);
    animation.setStep(1);
    expect(animation.sample(0)).toMatchObject({ phase: 'rising', index: 1 });
    expect(nodes.get('wall-001')!.scale.y).toBe(0);
    animation.restore();
    expect(nodes.get('wall-001')!.scale.y).toBe(3);
  });

  it('reaches done on timers alone, without animation frames', () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'performance'] });
    try {
      const { scene, nodes } = sceneOf(plan);
      const animation = createBuildAnimation(scene, performance.now());
      const sample = vi.fn(() => animation.sample(performance.now()));
      expect(sample().phase).toBe('flat');
      const cancel = scheduleBuildTransitions(sample, animation.timeline(performance.now()));
      vi.advanceTimersByTime(FLAT_DURATION_MS + 2);
      expect(sample.mock.results.at(-1)!.value.phase).toBe('rising');
      vi.advanceTimersByTime(animation.stepMs * 3 + 2);
      expect(sample.mock.results.at(-1)!.value).toMatchObject({ phase: 'done', progress: 1 });
      expect(nodes.get('wall-001')!.scale.y).toBe(3);
      cancel();
      const stop = scheduleBuildTransitions(vi.fn(), { introMs: 5, finishMs: 10 });
      stop();
      expect(vi.getTimerCount()).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('answer evidence → 3D highlight', () => {
  const answer: VisualiseAnswer = {
    doc_ids: ['other-document'],
    evidence: {
      scene: {
        doc_id: 'cubicasa5k__colorful-11397',
        highlight_item_ids: ['window-005', 'window-001', 'window-005'],
        camera_target_item_id: 'window-001',
      },
      boxes: [
        { item_id: 'window-001', label: '1' },
        { item_id: 'window-005', label: '5' },
        { item_id: 'window-005', label: '6' },
        { item_id: 'wall-001', label: '7' },
      ],
    },
  };

  it('uses the scene document, deduplicates IDs and preserves citation numbers rather than renumbering', () => {
    expect(answerToVisualise(answer)).toEqual({
      docId: 'cubicasa5k__colorful-11397', highlight: ['window-005', 'window-001'],
      labels: { 'window-001': '1', 'window-005': '5' }, cameraTargetItemId: 'window-001',
    });
    expect(answer.evidence.scene.highlight_item_ids).toHaveLength(3);
  });

  it('allows a document without any answer highlights and an empty-document disabled button', () => {
    const evidence = { scene: { doc_id: '', highlight_item_ids: [] }, boxes: [] };
    expect(answerToVisualise({ doc_ids: ['fallback'], evidence }).docId).toBe('fallback');
    expect(answerToVisualise({ doc_ids: [], evidence })).toEqual({
      docId: '', highlight: [], labels: {}, cameraTargetItemId: undefined,
    });
  });
});
