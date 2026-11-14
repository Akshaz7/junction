import {
  Box3, BufferAttribute, BufferGeometry, Group, MaterialLoader, Mesh, Sphere, Vector3,
  type Material, type Object3D, type TypedArray,
} from 'three';
import type { GLTF } from 'three/examples/jsm/loaders/GLTFLoader.js';

interface AttributeData { array: TypedArray; itemSize: number; normalized: boolean }
interface GeometryData {
  attributes: Record<string, AttributeData>;
  index: AttributeData | null;
  groups: { start: number; count: number; materialIndex?: number }[];
  drawRange: { start: number; count: number };
  box: number[];
  sphere: number[];
}
interface NodeData {
  parent: number;
  name: string;
  originalName?: string;
  matrix: number[];
  visible: boolean;
  geometry?: number;
  material?: number | number[];
}
export interface StaticGLTFData {
  nodes: NodeData[];
  geometries: GeometryData[];
  materials: ReturnType<Material['toJSON']>[];
}

/** Static, untextured IFC geometry only. Other glTF features use GLTFLoader directly. */
export function transferStaticGLTF(gltf: GLTF): { data: StaticGLTFData; buffers: ArrayBuffer[] } {
  const buffers = new Set<ArrayBuffer>();
  const geometries = new Map<BufferGeometry, number>();
  const materials = new Map<Material, number>();
  const nodes = new Map<Object3D, number>();
  const data: StaticGLTFData = { nodes: [], geometries: [], materials: [] };
  const attribute = (value: BufferAttribute): AttributeData => {
    if (!(value instanceof BufferAttribute)) throw new Error('Interleaved geometry needs the general glTF loader');
    buffers.add(value.array.buffer as ArrayBuffer);
    return { array: value.array, itemSize: value.itemSize, normalized: value.normalized };
  };
  gltf.scene.traverse((object) => {
    const mesh = object as Mesh;
    if (!mesh.isMesh && object.type !== 'Group' && object.type !== 'Object3D') {
      throw new Error('Non-static nodes need the general glTF loader');
    }
    if ((mesh as Mesh & { isSkinnedMesh?: boolean }).isSkinnedMesh || mesh.morphTargetInfluences) {
      throw new Error('Animated geometry needs the general glTF loader');
    }
    const association = gltf.parser.associations.get(object);
    const originalName = association?.nodes === undefined ? undefined : gltf.parser.json.nodes?.[association.nodes]?.name;
    object.updateMatrix();
    const node: NodeData = { parent: nodes.get(object.parent!) ?? -1, name: object.name,
      originalName, matrix: object.matrix.toArray(), visible: object.visible };
    if (mesh.isMesh) {
      const geometry = mesh.geometry;
      if (!geometries.has(geometry)) {
        geometry.computeBoundingBox();
        geometry.computeBoundingSphere();
        geometries.set(geometry, data.geometries.length);
        data.geometries.push({
          attributes: Object.fromEntries(Object.entries(geometry.attributes).map(([name, value]) =>
            [name, attribute(value as BufferAttribute)])),
          index: geometry.index ? attribute(geometry.index) : null,
          groups: geometry.groups, drawRange: geometry.drawRange,
          box: [...geometry.boundingBox!.min.toArray(), ...geometry.boundingBox!.max.toArray()],
          sphere: [...geometry.boundingSphere!.center.toArray(), geometry.boundingSphere!.radius],
        });
      }
      node.geometry = geometries.get(geometry)!;
      const materialIndex = (material: Material) => {
        if (!materials.has(material)) {
          materials.set(material, data.materials.length);
          data.materials.push(material.toJSON());
        }
        return materials.get(material)!;
      };
      node.material = Array.isArray(mesh.material) ? mesh.material.map(materialIndex) : materialIndex(mesh.material);
    }
    nodes.set(object, data.nodes.length);
    data.nodes.push(node);
  });
  return { data, buffers: [...buffers] };
}

/** Typed geometry buffers transfer ownership; no JSON number arrays or duplicate mesh bytes. */
export async function restoreStaticGLTF(data: StaticGLTFData, signal?: AbortSignal): Promise<Pick<GLTF, 'scene' | 'parser'>> {
  const check = () => signal?.throwIfAborted();
  const materialLoader = new MaterialLoader();
  const materials = data.materials.map((material) => materialLoader.parse(material));
  const geometries: BufferGeometry[] = [];
  const nodes: Object3D[] = [];
  const associations = new Map<Object3D, { nodes: number }>();
  let lastYield = performance.now();
  const yieldToBrowser = async () => {
    if (performance.now() - lastYield < 8) return;
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
    check();
    lastYield = performance.now();
  };
  try {
    for (const value of data.geometries) {
      check();
      const geometry = new BufferGeometry();
      geometries.push(geometry);
      for (const [name, attr] of Object.entries(value.attributes)) {
        geometry.setAttribute(name, new BufferAttribute(attr.array, attr.itemSize, attr.normalized));
      }
      if (value.index) geometry.setIndex(new BufferAttribute(value.index.array, value.index.itemSize, value.index.normalized));
      geometry.groups = value.groups;
      geometry.drawRange = value.drawRange;
      geometry.boundingBox = new Box3(new Vector3().fromArray(value.box), new Vector3().fromArray(value.box, 3));
      geometry.boundingSphere = new Sphere(new Vector3().fromArray(value.sphere), value.sphere[3]);
      await yieldToBrowser();
    }
    for (const [index, value] of data.nodes.entries()) {
      check();
      const material = Array.isArray(value.material) ? value.material.map((i) => materials[i])
        : materials[value.material ?? 0];
      const object = value.geometry === undefined ? new Group() : new Mesh(geometries[value.geometry], material);
      object.name = value.name;
      object.visible = value.visible;
      object.matrix.fromArray(value.matrix).decompose(object.position, object.quaternion, object.scale);
      object.frustumCulled = true;
      nodes.push(object);
      if (value.parent >= 0) nodes[value.parent].add(object);
      if (value.originalName !== undefined) associations.set(object, { nodes: index });
      await yieldToBrowser();
    }
    check();
    return { scene: nodes[0] as Group,
      parser: { associations, json: { nodes: data.nodes.map((node) => ({ name: node.originalName })) } } as GLTF['parser'] };
  } catch (error) {
    geometries.forEach((geometry) => geometry.dispose());
    materials.forEach((material) => material.dispose());
    throw error;
  }
}
