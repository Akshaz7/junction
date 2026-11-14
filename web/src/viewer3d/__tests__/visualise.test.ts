// @vitest-environment node
import { describe, expect, it, vi } from 'vitest';
import { Group, Object3D } from 'three';
import type { GLTF } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { createScene, type SceneManifest } from '../scene';
import { createRiseAnimation, FLAT_DURATION_MS, RISE_DURATION_MS, riseState, scheduleRiseTransitions } from '../rise';
import { answerToVisualise, type VisualiseAnswer } from '../visualise';

describe('flat → rising → done', () => {
  it('holds the plan, eases over 1.2 seconds, and clamps at done', () => {
    expect(riseState(0)).toEqual({ phase: 'flat', progress: 0 });
    expect(riseState(FLAT_DURATION_MS)).toEqual({ phase: 'flat', progress: 0 });
    const early = riseState(FLAT_DURATION_MS + RISE_DURATION_MS / 4);
    expect(early.phase).toBe('rising');
    expect(early.progress).toBeCloseTo(0.15625);
    expect(riseState(FLAT_DURATION_MS + RISE_DURATION_MS / 2)).toEqual({ phase: 'rising', progress: 0.5 });
    expect(riseState(FLAT_DURATION_MS + RISE_DURATION_MS)).toEqual({ phase: 'done', progress: 1 });
    expect(riseState(100_000)).toEqual({ phase: 'done', progress: 1 });
  });

  it('scales only architectural nodes, preserving original transforms and the plan floor', () => {
    const root = new Group();
    const ids = ['wall', 'door', 'window', 'room', 'plan_floor'];
    const nodes = ids.map((id, index) => {
      const node = new Object3D();
      node.name = id;
      node.position.set(index, 2, 3);
      node.scale.set(2, index + 2, 4);
      root.add(node);
      return node;
    });
    const manifest: SceneManifest = {
      doc_id: 'generated-for-demo', glb: '', usdz: null, units: 'm', up: 'Y',
      origin_offset_m: [0, 0, 0], storeys: [],
      items: Object.fromEntries(ids.slice(0, 4).map((id) => [id, {
        node: id, kind: id, usd_name: id, storey: null, bbox_m: null,
      }])),
    };
    const scene = createScene(manifest, {
      scene: root, parser: { associations: new Map(), json: {} } as unknown as GLTF['parser'],
    });
    const start = 100;
    const animation = createRiseAnimation(scene, start);
    animation.sample(start);
    expect(nodes.map((node) => node.scale.y)).toEqual([0, 0, 0, 5, 6]);
    animation.sample(start + FLAT_DURATION_MS + RISE_DURATION_MS / 2);
    expect(nodes.map((node) => node.scale.y)).toEqual([1, 1.5, 2, 5, 6]);
    animation.restore();
    expect(nodes.map((node) => node.scale.y)).toEqual([2, 3, 4, 5, 6]);
    nodes.forEach((node, index) => {
      expect(node.position.toArray()).toEqual([index, 2, 3]);
      expect(node.scale.x).toBe(2);
      expect(node.scale.z).toBe(4);
    });
    animation.sample(start + FLAT_DURATION_MS + RISE_DURATION_MS);
    expect(nodes.map((node) => node.scale.y)).toEqual([2, 3, 4, 5, 6]);
    const reduced = createRiseAnimation(scene, start, true);
    expect(reduced.sample(start)).toEqual({ phase: 'done', progress: 1 });
    expect(nodes.map((node) => node.scale.y)).toEqual([2, 3, 4, 5, 6]);
  });

  it('skips both flat and rising for reduced motion', () => {
    expect(riseState(0, true)).toEqual({ phase: 'done', progress: 1 });
  });

  it('reaches done and restores geometry without any animation frames', () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'performance'] });
    try {
      const root = new Group();
      const wall = new Object3D();
      wall.name = 'wall-001';
      wall.scale.y = 3;
      root.add(wall);
      const manifest: SceneManifest = {
        doc_id: 'generated-for-demo', glb: '', usdz: null, units: 'm', up: 'Y',
        origin_offset_m: [0, 0, 0], storeys: [],
        items: { 'wall-001': { node: wall.name, kind: 'wall', usd_name: 'wall', storey: null, bbox_m: null } },
      };
      const scene = createScene(manifest, {
        scene: root, parser: { associations: new Map(), json: {} } as unknown as GLTF['parser'],
      });
      const animation = createRiseAnimation(scene, performance.now());
      const sample = vi.fn(() => animation.sample(performance.now()));
      expect(sample().phase).toBe('flat');
      expect(wall.scale.y).toBe(0);
      const cancel = scheduleRiseTransitions(sample);
      vi.advanceTimersByTime(FLAT_DURATION_MS + 1);
      expect(sample.mock.results.at(-1)!.value.phase).toBe('rising');
      vi.advanceTimersByTime(RISE_DURATION_MS - 1);
      expect(sample.mock.results.at(-1)!.value).toEqual({ phase: 'done', progress: 1 });
      expect(wall.scale.y).toBe(3);
      cancel();

      const afterDispose = vi.fn();
      const stop = scheduleRiseTransitions(afterDispose);
      stop();
      vi.advanceTimersByTime(FLAT_DURATION_MS + RISE_DURATION_MS);
      expect(afterDispose).not.toHaveBeenCalled();
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
