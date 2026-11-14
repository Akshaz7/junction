import { Object3D, Texture, type Material, type Mesh } from 'three';
import { GLTFLoader, type GLTF } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { indexElements, type IFCElement } from './identify';

export type Vec3 = [number, number, number];
export type Storey = string | { name: string; elevation_m?: number };
export type SceneAsset = string | { url?: string; path?: string; local_path?: string };

export interface SceneItem {
  node: string;
  usd_name: string;
  bbox_m: [Vec3, Vec3] | null;
  storey: Storey | null;
  kind: string;
}

/** CONTRACT 5.5: geometry is already in metres, Y up, with its origin applied. */
export interface SceneManifest {
  doc_id: string;
  glb: SceneAsset;
  usdz: SceneAsset | null;
  units: 'm';
  up: 'Y';
  origin_offset_m: Vec3;
  storeys: Storey[];
  plan_image?: SceneAsset | null;
  items: Record<string, SceneItem>;
}

export interface LoadedScene {
  elements?: Map<string, IFCElement>;
  manifest: SceneManifest;
  root: Object3D;
  items: Map<string, Object3D>;
  /** Non-rendered IFC spaces/openings may be listed without a GLB node. */
  missingItemIds: string[];
  originalVisibility: Map<Object3D, boolean>;
  itemIdsByObject: Map<Object3D, string>;
}

export function storeyName(storey: Storey | null): string | null {
  return typeof storey === 'string' ? storey : storey?.name ?? null;
}

export function createScene(manifest: SceneManifest, gltf: Pick<GLTF, 'scene' | 'parser'>): LoadedScene {
  const nodes = new Map<string, Object3D>();
  const originalVisibility = new Map<Object3D, boolean>();
  gltf.scene.traverse((object) => {
    if (object.name) nodes.set(object.name, object);
    originalVisibility.set(object, object.visible);
  });
  // GLTFLoader sanitizes names (e.g. dots in plan-map IDs). Resolve the original
  // glTF node name via parser associations as well, preserving contract IDs.
  for (const [object, association] of gltf.parser.associations) {
    if (!(object instanceof Object3D) || association.nodes === undefined) continue;
    const name = gltf.parser.json.nodes?.[association.nodes]?.name;
    if (typeof name === 'string') nodes.set(name, object);
  }
  const items = new Map<string, Object3D>();
  const missingItemIds: string[] = [];
  const itemIdsByObject = new Map<Object3D, string>();
  for (const [id, item] of Object.entries(manifest.items)) {
    const object = nodes.get(item.node);
    if (!object) {
      missingItemIds.push(id);
      continue;
    }
    items.set(id, object);
    itemIdsByObject.set(object, id);
  }
  return { manifest, root: gltf.scene, items, missingItemIds, originalVisibility, itemIdsByObject };
}

export function documentSceneUrl(doc_id: string): string {
  return `/api/docs/${encodeURIComponent(doc_id)}/scene`;
}

/** API manifests contain filesystem paths, so their assets use the files route. */
export function documentFileUrl(manifestUrl: string | URL, name: string): string | null {
  const base = typeof location === 'undefined' ? undefined : location.href;
  const url = new URL(manifestUrl, base);
  if (!/^\/api\/docs\/[^/]+\/(?:scene|files\/scene\.json)$/.test(url.pathname)) return null;
  url.pathname = url.pathname.replace(/\/(?:scene|files\/scene\.json)$/, `/files/${name}`);
  url.search = '';
  url.hash = '';
  return url.href;
}

export class SceneLoadError extends Error {
  constructor(readonly status: number) {
    super(`Could not load scene manifest (${status})`);
  }
}

/** Loads scene.json; API assets use the file route, offline assets stay relative. */
export async function loadScene(manifestUrl: string | URL): Promise<LoadedScene> {
  const base = typeof location === 'undefined' ? undefined : location.href;
  const url = new URL(manifestUrl, base);
  const response = await fetch(url);
  if (!response.ok) throw new SceneLoadError(response.status);
  const manifest = await response.json() as SceneManifest;
  if (manifest.units !== 'm' || manifest.up !== 'Y' || !manifest.items) {
    throw new Error('Scene must use CONTRACT 5.5: metres, Y up, and an items map');
  }
  const asset = manifest.glb;
  const glb = typeof asset === 'string' ? asset : asset?.url || asset?.path || asset?.local_path;
  if (!glb) throw new Error('Scene manifest has no GLB path or URL');
  const elementsUrl = documentFileUrl(url, 'elements.json');
  const [gltf, elements] = await Promise.all([
    new GLTFLoader().loadAsync(documentFileUrl(url, 'scene.glb') ?? new URL(glb, response.url || url).href),
    elementsUrl ? fetch(elementsUrl).then(async (result) => result.ok
      ? indexElements(await result.json()) : new Map<string, IFCElement>()).catch(() => new Map<string, IFCElement>())
      : Promise.resolve(new Map<string, IFCElement>()),
  ]);
  return { ...createScene(manifest, gltf), elements };
}

/** Null restores each item's original visibility. Unassigned items hide for a named storey. */
export function setStorey(scene: LoadedScene, name: string | null): void {
  for (const [object, visible] of scene.originalVisibility) object.visible = visible;
  for (const [id, object] of scene.items) {
    object.visible = scene.originalVisibility.get(object) !== false
      && (name === null || storeyName(scene.manifest.items[id]!.storey) === name);
  }
  // A selected nested item still needs its container nodes to be visible.
  for (const object of scene.items.values()) {
    if (!object.visible) continue;
    for (let parent = object.parent; parent && parent !== scene.root; parent = parent.parent) {
      if (scene.originalVisibility.get(parent) !== false) parent.visible = true;
    }
  }
}

/** Resolves child meshes to the nearest manifest item; invisible ancestors cannot be picked. */
export function itemIdForObject(scene: LoadedScene, object: Object3D): string | null {
  let id: string | null = null;
  for (let current: Object3D | null = object; current; current = current.parent) {
    if (!current.visible) return null;
    id ??= scene.itemIdsByObject.get(current) ?? null;
  }
  return id;
}

export function disposeScene(scene: LoadedScene): void {
  const geometries = new Set<Mesh['geometry']>();
  const materials = new Set<Material>();
  const textures = new Set<Texture>();
  scene.root.traverse((object) => {
    const mesh = object as Mesh;
    if (mesh.geometry) geometries.add(mesh.geometry);
    if (mesh.material) {
      for (const material of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) {
        materials.add(material);
        for (const value of Object.values(material)) if (value instanceof Texture) textures.add(value);
      }
    }
  });
  textures.forEach((texture) => texture.dispose());
  materials.forEach((material) => material.dispose());
  geometries.forEach((geometry) => geometry.dispose());
}
