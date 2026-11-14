// @vitest-environment node
import { readFile } from 'node:fs/promises';
import { Box3, Mesh, Raycaster, Vector3 } from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { describe, expect, it } from 'vitest';
import { restoreStaticGLTF, transferStaticGLTF } from '../gltfTransfer';
import { createScene, disposeScene, itemIdForObject, type SceneManifest } from '../scene';

describe('static worker geometry transfer', () => {
  it('preserves the real fixture item IDs, bounds, shared buffers and raycast geometry after ownership transfer', async () => {
    const url = new URL('../__fixtures__/digital_hub/scene.json', import.meta.url);
    const manifest = JSON.parse(await readFile(url, 'utf8')) as SceneManifest;
    const bytes = await readFile(new URL(manifest.glb as string, url));
    const gltf = await new GLTFLoader().parseAsync(
      bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer, '');
    const original = createScene(manifest, gltf);
    const bounds = new Box3().setFromObject(original.root);
    const source = transferStaticGLTF(gltf);
    expect(source.buffers.length).toBeGreaterThan(0);
    expect(new Set(source.buffers).size).toBe(source.buffers.length);
    // Exercise the same structured-clone/ownership boundary as Worker.postMessage.
    const transferred = structuredClone(source.data, { transfer: source.buffers });
    expect(source.buffers.every((buffer) => buffer.byteLength === 0)).toBe(true);
    const restored = createScene(manifest, await restoreStaticGLTF(transferred));
    expect([...restored.items.keys()]).toEqual([...original.items.keys()]);
    expect(restored.missingItemIds).toEqual(original.missingItemIds);
    const actual = new Box3().setFromObject(restored.root);
    expect(actual.min.distanceTo(bounds.min)).toBeLessThan(1e-6);
    expect(actual.max.distanceTo(bounds.max)).toBeLessThan(1e-6);
    let mesh: Mesh | undefined;
    restored.root.traverse((object) => { if (!mesh && object instanceof Mesh) mesh = object; });
    expect(mesh).toBeDefined();
    const position = mesh!.geometry.getAttribute('position');
    const index = mesh!.geometry.getIndex();
    const a = new Vector3().fromBufferAttribute(position, index?.getX(0) ?? 0).applyMatrix4(mesh!.matrixWorld);
    const b = new Vector3().fromBufferAttribute(position, index?.getX(1) ?? 1).applyMatrix4(mesh!.matrixWorld);
    const c = new Vector3().fromBufferAttribute(position, index?.getX(2) ?? 2).applyMatrix4(mesh!.matrixWorld);
    const center = a.clone().add(b).add(c).divideScalar(3);
    const normal = b.clone().sub(a).cross(c.clone().sub(a)).normalize();
    const ray = new Raycaster(center.clone().add(normal), normal.negate());
    const hit = ray.intersectObject(mesh!, false)[0];
    expect(hit).toBeDefined();
    expect(itemIdForObject(restored, hit.object)).toBe(itemIdForObject(restored, mesh!));
    expect(itemIdForObject(restored, hit.object)).not.toBeNull();
    disposeScene(restored);
    // The original's geometry buffers are detached, but disposal is still valid.
    disposeScene(original);
  });

  it('stops hydration when the scene has been cancelled', async () => {
    const controller = new AbortController();
    controller.abort(new Error('Scene load expired'));
    await expect(restoreStaticGLTF({ nodes: [], geometries: [], materials: [] }, controller.signal))
      .rejects.toThrow('Scene load expired');
  });
});
