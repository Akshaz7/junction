// @vitest-environment node
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { Group } from 'three';
import { GLTFLoader, type GLTF } from 'three/examples/jsm/loaders/GLTFLoader.js';
import {
  createScene, disposeScene, itemIdForObject, loadScene, setStorey, storeyName,
  type LoadedScene, type SceneManifest,
} from '../scene';

const fixtureUrl = new URL('../__fixtures__/digital_hub/scene.json', import.meta.url);
let loaded: LoadedScene;
let manifest: SceneManifest;

beforeAll(async () => {
  manifest = JSON.parse(await readFile(fixtureUrl, 'utf8')) as SceneManifest;
  const bytes = await readFile(new URL(manifest.glb as string, fixtureUrl));
  const buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
  const gltf = await new Promise<GLTF>((resolve, reject) => {
    new GLTFLoader().parse(buffer, '', resolve, reject);
  });
  loaded = createScene(manifest, gltf);
});

afterEach(() => {
  setStorey(loaded, null);
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
afterAll(() => disposeScene(loaded));

describe('Digital Hub scene (real GLB, no WebGL)', () => {
  it('resolves five IFC GlobalIds through manifest node names', () => {
    const ids = [
      '3BmeJtEDj3AQO77Os2w7Ny',
      '3BmeJtEDj3AQO77Os2w7Gv',
      '23Np8uMAvEN9H6Ds49dht_',
      '23Np8uMAvEN9H6Ds49dhta',
      '23Np8uMAvEN9H6Ds49dhs8',
    ];
    expect(ids).toHaveLength(5);
    for (const id of ids) {
      const object = loaded.items.get(id);
      expect(object, id).toBeDefined();
      expect(object!.name).toBe(manifest.items[id]!.node);
      expect(itemIdForObject(loaded, object!)).toBe(id);
      expect(manifest.items[id]!.usd_name).toBe(`i_${createHash('sha1').update(id).digest('hex').slice(0, 16)}`);
    }
  });

  it('filters every resolved item by storey and restores the complete scene', () => {
    const storeys = new Set(Array.from(loaded.items.keys(), (id) => storeyName(manifest.items[id]!.storey)));
    expect(storeys.size).toBeGreaterThan(1);
    for (const name of storeys) {
      if (name === null) continue;
      setStorey(loaded, name);
      let visible = 0;
      let hidden = 0;
      for (const [id, object] of loaded.items) {
        const matches = storeyName(manifest.items[id]!.storey) === name;
        expect(object.visible, id).toBe(matches);
        if (matches) visible++;
        else {
          hidden++;
          expect(itemIdForObject(loaded, object)).toBeNull();
        }
      }
      expect(visible).toBeGreaterThan(0);
      expect(hidden).toBeGreaterThan(0);
    }
    setStorey(loaded, null);
    for (const object of loaded.items.values()) expect(object.visible).toBe(true);
    setStorey(loaded, 'storey-that-does-not-exist');
    for (const object of loaded.items.values()) expect(object.visible).toBe(false);
  });

  it('resolves child meshes and rejects items inside an invisible ancestor', () => {
    const [id, object] = loaded.items.entries().next().value!;
    const child = new Group();
    object.add(child);
    expect(itemIdForObject(loaded, child)).toBe(id);
    loaded.root.visible = false;
    expect(itemIdForObject(loaded, child)).toBeNull();
    loaded.root.visible = true;
    object.remove(child);
  });

  it('reports items omitted from the GLB instead of inventing geometry', () => {
    expect(loaded.missingItemIds.length).toBeGreaterThan(0);
    expect(loaded.items.size + loaded.missingItemIds.length).toBe(Object.keys(manifest.items).length);
    for (const id of loaded.missingItemIds) expect(loaded.items.has(id)).toBe(false);
  });

  it('loads the GLB URL relative to the scene manifest URL', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true, url: 'https://example.test/docs/digital-hub/scene.json', json: async () => manifest,
    }));
    const load = vi.spyOn(GLTFLoader.prototype, 'loadAsync').mockResolvedValue({
      scene: new Group(), parser: { associations: new Map(), json: {} },
    } as unknown as GLTF);
    await loadScene('https://example.test/api/scene');
    expect(load).toHaveBeenCalledWith('https://example.test/docs/digital-hub/scene.glb');
  });

  it('rejects failed manifest requests and non-contract coordinate systems', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 404 })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ ...manifest, up: 'Z' }) });
    vi.stubGlobal('fetch', fetchMock);
    await expect(loadScene('https://example.test/scene.json')).rejects.toThrow('404');
    await expect(loadScene('https://example.test/scene.json')).rejects.toThrow('Y up');
  });
});
