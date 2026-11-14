import { describe, expect, it, vi } from 'vitest';
import { BatchedMesh, BoxGeometry, Group, InstancedMesh, Matrix4, Mesh, MeshStandardMaterial, Raycaster, Vector3 } from 'three';
import { createRenderBatches, PICK_LAYER } from '../renderBatches';
import { createScene, disposeScene, itemIdForObject, type SceneManifest } from '../scene';
import { createHighlightController } from '../highlight';

function fixture(count: number, repeated: boolean) {
  const root = new Group();
  const material = new MeshStandardMaterial();
  const items: SceneManifest['items'] = {};
  for (let i = 0; i < count; i++) {
    const id = `wall-${i}`;
    // Different geometry instances with equal bytes must still share an instance buffer.
    const mesh = new Mesh(new BoxGeometry(repeated ? 1 : 1 + i / 1000, 1, 1), material);
    mesh.name = id;
    mesh.position.x = i * 2;
    root.add(mesh);
    items[id] = { node: id, kind: 'wall', bbox_m: null, storey: null, usd_name: id };
  }
  const manifest: SceneManifest = { doc_id: 'generated-for-demo', glb: 'scene.glb', usdz: null,
    units: 'm', up: 'Y', origin_offset_m: [0, 0, 0], storeys: [], items };
  return createScene(manifest, { scene: root, parser: { associations: new Map(), json: {} } } as Parameters<typeof createScene>[1]);
}

describe('large-scene render buffers preserve original item interactions', () => {
  it('leaves small scenes on their original rendering path', () => {
    const scene = fixture(3, true);
    const batches = createRenderBatches(scene);
    expect(batches.root.children).toHaveLength(0);
    expect(scene.items.get('wall-0')!.layers.mask).toBe(1);
    batches.dispose(); disposeScene(scene);
  });

  it('instances exact repeats while original item IDs remain raycastable', () => {
    const scene = fixture(500, true);
    const batches = createRenderBatches(scene);
    batches.sync();
    expect(batches.root.children).toHaveLength(1);
    expect(batches.root.children[0]).toBeInstanceOf(InstancedMesh);
    expect((batches.root.children[0] as InstancedMesh).count).toBe(500);
    const ray = new Raycaster(new Vector3(0, 0, 5), new Vector3(0, 0, -1));
    ray.layers.enable(PICK_LAYER);
    const hit = ray.intersectObject(scene.root, true)[0];
    expect(itemIdForObject(scene, hit.object)).toBe('wall-0');
    const mesh = scene.items.get('wall-0') as Mesh;
    mesh.visible = false;
    batches.sync();
    const matrix = new Matrix4();
    (batches.root.children[0] as InstancedMesh).getMatrixAt(0, matrix);
    expect(matrix.determinant()).toBe(0);
    expect(itemIdForObject(scene, mesh)).toBeNull();
    batches.dispose();
    expect(mesh.layers.mask).toBe(1);
    disposeScene(scene);
  });

  it('batches different geometry by material, follows transforms/visibility, and disposes only owned buffers', () => {
    const scene = fixture(500, false);
    const batches = createRenderBatches(scene);
    const batch = batches.root.children[0] as BatchedMesh;
    expect(batch).toBeInstanceOf(BatchedMesh);
    expect(batch.perObjectFrustumCulled).toBe(true);
    const source = scene.items.get('wall-0') as Mesh;
    source.position.y = 3;
    batches.sync();
    const matrix = new Matrix4();
    batch.getMatrixAt(0, matrix);
    expect(matrix.elements[13]).toBe(3);
    scene.root.visible = false;
    batches.sync();
    expect(batch.getVisibleAt(0)).toBe(false);
    scene.root.visible = true;
    batches.sync();
    expect(batch.getVisibleAt(0)).toBe(true);
    const sourceDispose = vi.spyOn(source.geometry, 'dispose');
    const bufferDispose = vi.spyOn(batch.geometry, 'dispose');
    batches.dispose();
    expect(bufferDispose).toHaveBeenCalledOnce();
    expect(sourceDispose).not.toHaveBeenCalled();
    disposeScene(scene);
    expect(sourceDispose).toHaveBeenCalledOnce();
  });

  it('renders changed item materials through the original path and rejoins batches after highlight clears', () => {
    const scene = fixture(500, false);
    const batches = createRenderBatches(scene);
    const batch = batches.root.children[0] as BatchedMesh;
    const source = scene.items.get('wall-0') as Mesh;
    const highlights = createHighlightController(scene);
    highlights.highlight(['wall-0']);
    batches.sync();
    expect(batch.getVisibleAt(0)).toBe(false);
    expect(source.layers.mask & 1).toBe(1);
    expect((source.material as MeshStandardMaterial).emissiveIntensity).toBe(2.8);
    highlights.clearHighlight();
    batches.sync();
    expect(batch.getVisibleAt(0)).toBe(true);
    expect(source.layers.mask & 1).toBe(0);
    batches.dispose(); disposeScene(scene);
  });
});
