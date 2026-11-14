import {
  BatchedMesh, BufferAttribute, Group, InstancedMesh, Matrix4,
  type BufferGeometry, type Material, type Mesh, type Object3D,
} from 'three';
import type { LoadedScene } from './scene';

/** Originals retain their geometry, hierarchy and item IDs for all interaction layers. */
export const PICK_LAYER = 31;
const LARGE_SCENE_MESHES = 500;
const INSTANCE_MIN = 8;

interface GeometryGroup { geometry: BufferGeometry; meshes: Mesh[] }
interface Entry {
  source: Mesh;
  material: Material;
  layers: number;
  output: BatchedMesh | InstancedMesh;
  index: number;
}

function attributes(geometry: BufferGeometry): [string, BufferAttribute][] | null {
  const entries = Object.entries(geometry.attributes);
  if (geometry.index) entries.push(['index', geometry.index]);
  if (!entries.every(([, attribute]) => attribute instanceof BufferAttribute)) return null;
  return (entries as [string, BufferAttribute][]).sort(([a], [b]) => a.localeCompare(b));
}

function bytes(attribute: BufferAttribute): Uint8Array {
  const array = attribute.array;
  return new Uint8Array(array.buffer, array.byteOffset, array.byteLength);
}

function identical(a: BufferGeometry, b: BufferGeometry): boolean {
  if (a === b) return true;
  const left = attributes(a)!;
  const right = attributes(b)!;
  return left.every(([, attribute], i) => {
    const x = bytes(attribute), y = bytes(right[i][1]);
    if (x.length !== y.length) return false;
    for (let index = 0; index < x.length; index++) if (x[index] !== y[index]) return false;
    return true;
  });
}

function visible(object: Object3D): boolean {
  for (let node: Object3D | null = object; node; node = node.parent) if (!node.visible) return false;
  return true;
}

/**
 * A render-only sibling of the item tree. Exact geometry repeats use instancing;
 * other opaque static meshes share material/attribute batches. Picking always
 * raycasts the original item meshes. Changed materials temporarily render those
 * originals, preserving glow, dimming, isolation and opacity fades without
 * teaching those controllers about GPU batch indices.
 */
export function createRenderBatches(scene: LoadedScene) {
  const root = new Group();
  root.name = 'viewer-render-batches';
  const entries: Entry[] = [];
  const outputs: (BatchedMesh | InstancedMesh)[] = [];
  const meshes: Mesh[] = [];
  scene.root.updateWorldMatrix(true, true);
  scene.root.traverse((object) => {
    const mesh = object as Mesh;
    if (mesh.isMesh) meshes.push(mesh);
  });

  // Leave small scenes untouched; their existing per-item path is inexpensive.
  if (meshes.length >= LARGE_SCENE_MESHES) {
    const materials = new Map<string, { material: Material; groups: GeometryGroup[] }>();
    const fingerprints = new WeakMap<BufferGeometry, string>();
    const duplicates = new Map<string, GeometryGroup[]>();
    for (const mesh of meshes) {
      const geometry = mesh.geometry;
      const material = mesh.material;
      const attrs = attributes(geometry);
      if (Array.isArray(material) || material.transparent || mesh.name === 'plan_floor'
        || (mesh.layers.mask & 1) === 0
        || (mesh as Mesh & { isSkinnedMesh?: boolean }).isSkinnedMesh
        || (mesh as InstancedMesh).isInstancedMesh || (mesh as BatchedMesh).isBatchedMesh
        || Object.keys(geometry.morphAttributes).length || !attrs || !geometry.attributes.position
        || geometry.drawRange.start !== 0
        || geometry.drawRange.count < (geometry.index?.count ?? geometry.attributes.position.count)
        || mesh.matrixWorld.determinant() <= 0) continue;

      const layout = attrs.map(([name, attribute]) =>
        `${name}:${attribute.array.constructor.name}:${attribute.itemSize}:${attribute.normalized}`).join('|');
      const materialKey = `${material.uuid}:${layout}`;
      let fingerprint = fingerprints.get(geometry);
      if (!fingerprint) {
        let hash = 2166136261;
        for (const [, attribute] of attrs) {
          const data = bytes(attribute);
          for (let i = 0; i < data.length; i++) hash = Math.imul(hash ^ data[i], 16777619);
        }
        fingerprint = `${geometry.attributes.position.count}:${geometry.index?.count ?? 0}:${hash >>> 0}`;
        fingerprints.set(geometry, fingerprint);
      }
      const key = `${materialKey}:${fingerprint}`;
      const candidates = duplicates.get(key) ?? [];
      // Verify byte equality as well as the hash: collisions must never alter geometry.
      let group = candidates.find((candidate) => identical(candidate.geometry, geometry));
      if (!group) {
        group = { geometry, meshes: [] };
        candidates.push(group);
        duplicates.set(key, candidates);
        const bucket = materials.get(materialKey) ?? { material, groups: [] };
        bucket.groups.push(group);
        materials.set(materialKey, bucket);
      }
      group.meshes.push(mesh);
    }

    function bind(source: Mesh, output: Entry['output'], index: number, material: Material) {
      entries.push({ source, output, index, material, layers: source.layers.mask });
      source.layers.set(PICK_LAYER);
      output.setMatrixAt(index, source.matrixWorld);
    }

    try {
      for (const { material, groups } of materials.values()) {
        const remaining: GeometryGroup[] = [];
        for (const group of groups) {
          if (group.meshes.length < INSTANCE_MIN) { remaining.push(group); continue; }
          const instanced = new InstancedMesh(group.geometry, material, group.meshes.length);
          outputs.push(instanced);
          root.add(instanced);
          group.meshes.forEach((mesh, index) => bind(mesh, instanced, index, material));
          instanced.computeBoundingSphere();
        }
        const count = remaining.reduce((sum, group) => sum + group.meshes.length, 0);
        if (count < 2) continue;
        const vertices = remaining.reduce((sum, group) => sum + group.geometry.attributes.position.count, 0);
        const indices = remaining.reduce((sum, group) => sum + (group.geometry.index?.count ?? 0), 0);
        const batch = new BatchedMesh(count, vertices, indices, material);
        // Opaque meshes do not need per-frame depth sorting. Keep per-item culling.
        batch.sortObjects = false;
        batch.perObjectFrustumCulled = true;
        outputs.push(batch);
        root.add(batch);
        for (const group of remaining) {
          const geometryId = batch.addGeometry(group.geometry);
          for (const mesh of group.meshes) bind(mesh, batch, batch.addInstance(geometryId), material);
        }
      }
    } catch (error) {
      for (const entry of entries) entry.source.layers.mask = entry.layers;
      outputs.forEach((output) => output.dispose());
      throw error;
    }
  }

  const hidden = new Matrix4().makeScale(0, 0, 0);
  return {
    root,
    sync() {
      scene.root.updateWorldMatrix(true, true);
      for (const entry of entries) {
        const { source, material, output, index, layers } = entry;
        const batched = source.material === material;
        source.layers.mask = batched ? 1 << PICK_LAYER : layers | (1 << PICK_LAYER);
        const shown = batched && visible(source);
        if (output instanceof BatchedMesh) {
          output.setVisibleAt(index, shown);
          if (shown) output.setMatrixAt(index, source.matrixWorld);
        } else output.setMatrixAt(index, shown ? source.matrixWorld : hidden);
      }
      for (const output of outputs) {
        if (output instanceof InstancedMesh) {
          output.instanceMatrix.needsUpdate = true;
          // Bounds must enclose the current transforms (including rise animations).
          output.computeBoundingSphere();
        }
      }
    },
    dispose() {
      root.removeFromParent();
      for (const entry of entries) entry.source.layers.mask = entry.layers;
      // InstancedMesh owns its instance buffers; source geometry/materials are
      // disposed separately with the original scene. BatchedMesh owns its copies.
      outputs.forEach((output) => output.dispose());
      root.clear();
    },
  };
}
