import {
  BufferGeometry, CanvasTexture, Color, DoubleSide, Float32BufferAttribute, Group, LineBasicMaterial, LineSegments,
  Mesh, MeshBasicMaterial, type Camera, PlaneGeometry, SRGBColorSpace, Vector3, Box3,
  type Material, type Object3D,
} from 'three';
import { CSS2DObject } from 'three/examples/jsm/renderers/CSS2DRenderer.js';
import { storeyName, type LoadedScene, type SceneItem } from './scene';

/**
 * Blueprint layer: the 3D view carries what a 2D drawing carries (room names and areas, overall dimensions,
 * storey names) and per-element materials instead of one uniform grey. The rules and colours below are
 * mirrored by the iOS AR view; keep the README ("Blueprint layer") in sync when changing them.
 */
export const MATERIAL_COLORS: Record<string, string> = {
  wall: '#d9d4c9', door: '#9c6b3c', window: '#9fd3ea', slab: '#e6e2d9', site: '#cfc9bf', roof: '#9a8f86', stairs: '#5f5a54',
  column: '#bdb7ad', railing: '#8d99a6', furniture: '#b9ad9d',
  toilet: '#f4f7f9', sink: '#f4f7f9', shower: '#f4f7f9', bathtub: '#f4f7f9',
};
export const GLASS_OPACITY = 0.38;
/** Site/terrain is drawn faint so it never dominates the frame. */
export const SITE_OPACITY = 0.22;
/** Wall faces pointing up (the cut top) are multiplied by this, so walls read as a cut plan. */
export const WALL_TOP_DARKEN = 0.42;
export const ROOM_FLOOR_COLORS = { neutral: '#f1eee6', wet: '#cde3f3', kitchen: '#f4e4c9' } as const;
export type RoomClass = keyof typeof ROOM_FLOOR_COLORS;
/** A room label is hidden when its text would be smaller than this (metres) or the room is narrower than ROOM_MIN_M. */
export const ROOM_MIN_M = 1.2;
export const LABEL_MIN_HEIGHT_M = 0.14;
export const LABEL_MAX_HEIGHT_M = 0.9;
export const DIM_OFFSET_M = 1.2;
/** Rooms taller than this are volumes (IFC spaces) rather than flat floor patches. */
export const ROOM_VOLUME_M = 0.3;
const WET = /\b(wc|toilet|bath(room)?|shower|sauna|laundry|washroom|restroom|wash|utility)\b|bad\b|dusch|wasch|pesu|kylpy|suihku|\bph\b|\bkph\b|\bwc\b|lavat/i;
const KITCHEN = /kitchen|küche|kueche|keitti|kök|kitch|\bkk\b|\bkt\b|pantry|teekeitti/i;

/** Floor tint by room type (raster plans) or name (IFC): wet rooms bluish, kitchens warm, the rest neutral. */
export function classifyRoom(item: Pick<SceneItem, 'name' | 'props'>): RoomClass {
  const type = typeof item.props?.room_type === 'string' ? item.props.room_type : '';
  const text = `${type} ${item.name ?? ''}`.replace(/_/g, ' ');
  if (WET.test(text)) return 'wet';
  if (KITCHEN.test(text)) return 'kitchen';
  return 'neutral';
}

export function roomArea(item: Pick<SceneItem, 'props'>): number | null {
  const area = item.props?.area_m2;
  return typeof area === 'number' && Number.isFinite(area) && area > 0 ? area : null;
}

/** Text of a room label: the name (when known) and the area (only when the data carries it). */
export function roomLabelText(item: Pick<SceneItem, 'name' | 'props'>): { name: string | null; area: string | null } {
  const name = item.name?.trim() || null;
  const area = roomArea(item);
  return { name, area: area === null ? null : `${area.toFixed(1)} m²` };
}

export interface LabelFit { show: boolean; height: number; width: number; rotated: boolean }

/** Size of a flat room label (metres) from the room's footprint; hidden when it would be unreadably small. */
export function fitRoomLabel(footprintX: number, footprintZ: number, aspect: number): LabelFit {
  const short = Math.min(footprintX, footprintZ);
  if (short < ROOM_MIN_M) return { show: false, height: 0, width: 0, rotated: false };
  const rotated = footprintZ > footprintX * 1.6;
  const along = rotated ? footprintZ : footprintX;
  const across = rotated ? footprintX : footprintZ;
  let height = Math.min(LABEL_MAX_HEIGHT_M, Math.max(LABEL_MIN_HEIGHT_M, short * 0.2));
  let width = height * aspect;
  if (width > along * 0.9) { width = along * 0.9; height = width / aspect; }
  if (height > across * 0.6) { height = across * 0.6; width = height * aspect; }
  return height < LABEL_MIN_HEIGHT_M ? { show: false, height: 0, width: 0, rotated } : { show: true, height, width, rotated };
}

export function formatMetres(value: number): string { return `${value.toFixed(1)} m`; }
export function formatElevation(metres: number): string {
  const rounded = Math.round(metres * 100) / 100;
  return `${rounded < 0 ? '−' : '+'}${Math.abs(rounded).toFixed(2)} m`;
}

// ---- materials ----

type Styled = Material & { color?: Color; isMeshStandardMaterial?: boolean };

function patchWallTop(material: Styled): void {
  if (!material.isMeshStandardMaterial) return;
  const proto = Object.getPrototypeOf(material) as Material;
  material.onBeforeCompile = (shader) => {
    shader.fragmentShader = shader.fragmentShader.replace('#include <normal_fragment_maps>',
      `#include <normal_fragment_maps>\n  if (normalize((vec4(normal, 0.0) * viewMatrix).xyz).y > 0.85) diffuseColor.rgb *= ${WALL_TOP_DARKEN.toFixed(2)};`);
  };
  material.customProgramCacheKey = () => 'wall-cut-top';
  // Highlight and fade layers clone materials; the clone keeps the cut-top shading.
  material.clone = function (this: Material) { const copy = proto.clone.call(this) as Styled; patchWallTop(copy); return copy; };
}

function styleMaterial(kind: string, source: Material, floor: RoomClass | null): Material {
  const material = source.clone() as Styled;
  if (!material.color) return material;
  if (kind === 'room') material.color.set(ROOM_FLOOR_COLORS[floor ?? 'neutral']);
  else if (MATERIAL_COLORS[kind]) material.color.set(MATERIAL_COLORS[kind]);
  else return material;
  if (kind === 'window') {
    material.transparent = true; material.opacity = GLASS_OPACITY; material.depthWrite = false;
    const glass = material as Material & { roughness?: number; metalness?: number };
    if (glass.roughness !== undefined) glass.roughness = 0.1;
    if (glass.metalness !== undefined) glass.metalness = 0;
  }
  if (kind === 'wall') patchWallTop(material);
  if (kind === 'site') { material.transparent = true; material.opacity = SITE_OPACITY; material.depthWrite = false; }
  material.needsUpdate = true;
  return material;
}

/** Per-element materials. Run before any highlight/command layer captures the original materials. */
export function styleSceneMaterials(scene: LoadedScene): Record<string, string> {
  const cache = new Map<string, Material>();
  const applied: Record<string, string> = {};
  for (const [id, object] of scene.items) {
    const item = scene.manifest.items[id];
    if (!item) continue;
    const floor = item.kind === 'room' ? classifyRoom(item) : null;
    if (item.kind !== 'room' && !MATERIAL_COLORS[item.kind]) continue;
    object.traverse((node) => {
      const mesh = node as Mesh;
      if (!mesh.isMesh || mesh.name === 'plan_floor' || Array.isArray(mesh.material)) return;
      const key = `${item.kind}|${floor ?? ''}|${mesh.material.uuid}`;
      let material = cache.get(key);
      if (!material) { material = styleMaterial(item.kind, mesh.material, floor); cache.set(key, material); }
      mesh.material = material;
      applied[item.kind] = item.kind === 'room' ? ROOM_FLOOR_COLORS[floor ?? 'neutral'] : MATERIAL_COLORS[item.kind];
    });
  }
  return applied;
}

// ---- labels, dimensions, storey tags ----

function shown(object: Object3D): boolean {
  if (object.scale.y < 0.999) return false;
  for (let node: Object3D | null = object; node; node = node.parent) if (!node.visible) return false;
  return true;
}

function roomTexture(name: string | null, area: string | null): { texture: CanvasTexture; aspect: number } {
  const lines = [name, area].filter((line): line is string => !!line);
  const fontPx = 64;
  const probe = document.createElement('canvas').getContext('2d')!;
  probe.font = `700 ${fontPx}px system-ui, sans-serif`;
  const width = Math.ceil(Math.max(...lines.map((line, i) => { probe.font = `${i === 0 && name ? 700 : 500} ${fontPx}px system-ui, sans-serif`; return probe.measureText(line).width; }))) + 32;
  const height = lines.length * fontPx * 1.2 + 24;
  const canvas = document.createElement('canvas');
  canvas.width = width; canvas.height = height;
  const ctx = canvas.getContext('2d')!;
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.lineJoin = 'round';
  lines.forEach((line, i) => {
    const y = 12 + fontPx * 0.6 + i * fontPx * 1.2;
    ctx.font = `${i === 0 && name ? 700 : 500} ${fontPx}px system-ui, sans-serif`;
    ctx.lineWidth = 10; ctx.strokeStyle = 'rgba(255,255,255,0.92)'; ctx.strokeText(line, width / 2, y);
    ctx.fillStyle = i === 0 && name ? '#1f2937' : '#475569'; ctx.fillText(line, width / 2, y);
  });
  const texture = new CanvasTexture(canvas);
  texture.colorSpace = SRGBColorSpace; texture.anisotropy = 4;
  return { texture, aspect: width / height };
}

export interface BlueprintState {
  rooms: { id: string; name: string | null; area: string | null; floor: RoomClass; shown: boolean; hidden: 'small' | 'no-text' | null }[];
  dimensions: string[];
  storeys: { name: string; label: string; shown: boolean }[];
  materials: Record<string, string>;
}

export interface Blueprint {
  root: Group;
  /** True when any DOM label (dimensions, storeys) exists, so the label renderer must run. */
  hasLabels: boolean;
  update(now: number, camera: Camera, height: number): void;
  setVisible(visible: boolean): void;
  getState(): BlueprintState;
  dispose(): void;
}

export function createBlueprint(scene: LoadedScene, eye: Vector3, materials: Record<string, string>): Blueprint {
  const root = new Group();
  root.name = 'blueprint-layer';
  scene.root.updateWorldMatrix(true, true);
  const disposables: { dispose(): void }[] = [];
  const dom: CSS2DObject[] = [];
  const rooms: { id: string; mesh: Mesh | null; object: Object3D; info: BlueprintState['rooms'][number] }[] = [];

  // Room names and areas lying flat on each room's floor.
  for (const [id, item] of Object.entries(scene.manifest.items)) {
    if (item.kind !== 'room') continue;
    const object = scene.items.get(id);
    if (!object || !item.bbox_m) continue;
    const { name, area } = roomLabelText(item);
    const info = { id, name, area, floor: classifyRoom(item), shown: false, hidden: null as 'small' | 'no-text' | null };
    if (!name && !area) { info.hidden = 'no-text'; rooms.push({ id, mesh: null, object, info }); continue; }
    const [min, max] = item.bbox_m;
    const { texture, aspect } = roomTexture(name, area);
    const fit = fitRoomLabel(max[0] - min[0], max[2] - min[2], aspect);
    if (!fit.show) { texture.dispose(); info.hidden = 'small'; rooms.push({ id, mesh: null, object, info }); continue; }
    const geometry = new PlaneGeometry(fit.width, fit.height);
    const material = new MeshBasicMaterial({ map: texture, transparent: true, depthWrite: false, side: DoubleSide, toneMapped: false,
      polygonOffset: true, polygonOffsetFactor: -4, polygonOffsetUnits: -4 });
    disposables.push(geometry, material, texture);
    const mesh = new Mesh(geometry, material);
    mesh.name = `room-label:${id}`;
    mesh.renderOrder = 5;
    mesh.rotation.x = -Math.PI / 2;
    if (fit.rotated) mesh.rotation.z = Math.PI / 2;
    // IFC rooms are opaque volumes: the label goes on their top face (the visible one from above); raster rooms are flat.
    const y = max[1] - min[1] > ROOM_VOLUME_M ? max[1] + 0.03 : min[1] + 0.05;
    mesh.position.set((min[0] + max[0]) / 2, y, (min[2] + max[2]) / 2);
    root.add(mesh);
    rooms.push({ id, mesh, object, info });
  }

  // Overall dimensions (L x W) on the two outer edges facing the camera, from the walls' geometry.
  const dims: string[] = [];
  const bounds = overallBounds(scene);
  const dimensionLines: LineSegments[] = [];
  if (bounds) {
    const centre = bounds.getCenter(new Vector3());
    const zEdge = eye.z >= centre.z ? bounds.max.z : bounds.min.z;
    const xEdge = eye.x >= centre.x ? bounds.max.x : bounds.min.x;
    const zDir = eye.z >= centre.z ? 1 : -1;
    const xDir = eye.x >= centre.x ? 1 : -1;
    const y = baseY(scene, bounds) + 0.05;
    const lengthX = bounds.max.x - bounds.min.x;
    const lengthZ = bounds.max.z - bounds.min.z;
    const lineZ = zEdge + zDir * DIM_OFFSET_M;
    const lineX = xEdge + xDir * DIM_OFFSET_M;
    const positions: number[] = [];
    const seg = (a: Vector3, b: Vector3) => positions.push(a.x, a.y, a.z, b.x, b.y, b.z);
    const tick = 0.25;
    // Length along X, drawn parallel to the near z edge.
    seg(new Vector3(bounds.min.x, y, lineZ), new Vector3(bounds.max.x, y, lineZ));
    seg(new Vector3(bounds.min.x, y, zEdge), new Vector3(bounds.min.x, y, lineZ + zDir * tick));
    seg(new Vector3(bounds.max.x, y, zEdge), new Vector3(bounds.max.x, y, lineZ + zDir * tick));
    // Width along Z, drawn parallel to the near x edge.
    seg(new Vector3(lineX, y, bounds.min.z), new Vector3(lineX, y, bounds.max.z));
    seg(new Vector3(xEdge, y, bounds.min.z), new Vector3(lineX + xDir * tick, y, bounds.min.z));
    seg(new Vector3(xEdge, y, bounds.max.z), new Vector3(lineX + xDir * tick, y, bounds.max.z));
    const geometry = new BufferGeometry();
    geometry.setAttribute('position', new Float32BufferAttribute(positions, 3));
    const material = new LineBasicMaterial({ color: new Color('#334155') });
    disposables.push(geometry, material);
    const lines = new LineSegments(geometry, material);
    lines.name = 'blueprint-dimensions';
    root.add(lines);
    dimensionLines.push(lines);
    const addDim = (text: string, position: Vector3) => {
      const element = document.createElement('div');
      element.className = 'viewer3d-dim-label';
      element.textContent = text;
      const label = new CSS2DObject(element);
      label.position.copy(position);
      root.add(label);
      dom.push(label);
      dims.push(text);
    };
    addDim(formatMetres(lengthX), new Vector3((bounds.min.x + bounds.max.x) / 2, y, lineZ));
    addDim(formatMetres(lengthZ), new Vector3(lineX, y, (bounds.min.z + bounds.max.z) / 2));
  }

  // Storey name + elevation at the building's near-left corner, at each storey's floor level.
  const storeyTags: { name: string; label: string; element: HTMLElement; ids: string[]; shown: boolean; floorY: number; position: Vector3; object: CSS2DObject }[] = [];
  if (bounds) {
    const names = scene.manifest.storeys.map(storeyName).filter((n): n is string => !!n);
    for (const name of names) {
      const entry = scene.manifest.storeys.find((s) => storeyName(s) === name);
      const elevation = typeof entry === 'object' && entry && typeof entry.elevation_m === 'number' ? entry.elevation_m : null;
      const ids = Object.entries(scene.manifest.items).filter(([, it]) => storeyName(it.storey) === name && it.kind !== 'site').map(([id]) => id);
      if (!ids.length) continue;
      const floorY = elevation ?? Math.min(...ids.map((id) => scene.manifest.items[id].bbox_m?.[0][1] ?? Infinity).filter(Number.isFinite));
      if (!Number.isFinite(floorY)) continue;
      const label = elevation === null ? name : `${name} · ${formatElevation(elevation)}`;
      const element = document.createElement('div');
      element.className = 'viewer3d-storey-label';
      element.dataset.storey = name;
      element.textContent = label;
      const object = new CSS2DObject(element);
      object.position.set(bounds.min.x - 0.6, floorY + 0.05, bounds.max.z + 0.6);
      root.add(object);
      dom.push(object);
      storeyTags.push({ name, label, element, ids, shown: true, floorY, position: object.position, object });
    }
  }

  let lastCamera: Camera | null = null;
  let lastHeight = 0;
  const probe = new Vector3();
  /** Storey tags that would stack on top of each other on screen: keep the topmost only. */
  function thin(): void {
    const shownTags = storeyTags.filter((t) => t.shown);
    const kept: number[] = [];
    const ordered = lastCamera ? [...shownTags].sort((a, b) => b.floorY - a.floorY) : shownTags;
    for (const tag of ordered) {
      if (lastCamera) {
        probe.set(tag.position.x, tag.floorY + 0.05, tag.position.z).project(lastCamera);
        const y = (1 - probe.y) * lastHeight / 2;
        if (kept.some((k) => Math.abs(k - y) < 20)) { tag.shown = false; continue; }
        kept.push(y);
      }
    }
    // CSS2DRenderer owns element.style.display, so hide through the object.
    for (const tag of storeyTags) tag.object.visible = tag.shown;
  }

  let lastCheck = 0;
  let visibleAll = true;
  function refresh(): void {
    for (const room of rooms) {
      const on = visibleAll && shown(room.object);
      room.info.shown = !!room.mesh && on;
      if (room.mesh) room.mesh.visible = on;
    }
    for (const tag of storeyTags) {
      tag.shown = visibleAll && tag.ids.some((id) => { const o = scene.items.get(id); return !!o && shown(o); });
    }
    thin();
    for (const label of dom) if (label.element.classList.contains('viewer3d-dim-label')) label.visible = visibleAll;
    for (const lines of dimensionLines) lines.visible = visibleAll;
  }

  return {
    root,
    hasLabels: dom.length > 0,
    update(now, camera, height) { lastCamera = camera; lastHeight = height; if (now - lastCheck < 120) return; lastCheck = now; refresh(); },
    setVisible(visible) { visibleAll = visible; refresh(); },
    getState: () => ({
      rooms: rooms.map((r) => ({ ...r.info })),
      dimensions: [...dims],
      storeys: storeyTags.map(({ name, label, shown: s }) => ({ name, label, shown: s })),
      materials: { ...materials },
    }),
    dispose() {
      for (const label of dom) { label.removeFromParent(); label.element.remove(); }
      disposables.forEach((d) => d.dispose());
      root.removeFromParent();
    },
  };
}

function overallBounds(scene: LoadedScene): Box3 | null {
  for (const wanted of [['wall'], ['wall', 'slab']]) {
    const ids = Object.entries(scene.manifest.items).filter(([, it]) => wanted.includes(it.kind)).map(([id]) => id);
    const bounds = boundsOf(scene, ids);
    if (bounds) return bounds;
  }
  return null;
}

function boundsOf(scene: LoadedScene, ids: string[]): Box3 | null {
  const out = new Box3();
  for (const id of ids) { const o = scene.items.get(id); if (o) out.union(new Box3().setFromObject(o)); }
  return out.isEmpty() ? null : out;
}

/** Dimension lines sit at the ground storey's floor (or the lowest item when no elevation is known). */
function baseY(scene: LoadedScene, bounds: Box3): number {
  const elevations = scene.manifest.storeys.map((s) => typeof s === 'object' ? s.elevation_m : undefined)
    .filter((e): e is number => typeof e === 'number' && e >= 0);
  return elevations.length ? Math.min(...elevations) : bounds.min.y;
}

/** Callout tags are dropped above this many highlighted items (the per-kind glow and the legend carry the answer). */
export const MAX_CALLOUT_TAGS = 12;
const OVERSIZED_SLAB_FACTOR = 3;

/** Item ids that count for camera framing: never the site/terrain, nor a slab more than 3x the building footprint. */
export function framingIds(scene: LoadedScene): string[] {
  const entries = Object.entries(scene.manifest.items).filter(([id, it]) => it.kind !== 'site' && it.bbox_m && scene.items.has(id));
  const area = (it: SceneItem) => (it.bbox_m![1][0] - it.bbox_m![0][0]) * (it.bbox_m![1][2] - it.bbox_m![0][2]);
  const walls = entries.filter(([, it]) => it.kind === 'wall');
  let footprint = 0;
  if (walls.length) {
    const minX = Math.min(...walls.map(([, it]) => it.bbox_m![0][0])), maxX = Math.max(...walls.map(([, it]) => it.bbox_m![1][0]));
    const minZ = Math.min(...walls.map(([, it]) => it.bbox_m![0][2])), maxZ = Math.max(...walls.map(([, it]) => it.bbox_m![1][2]));
    footprint = (maxX - minX) * (maxZ - minZ);
  }
  return entries.filter(([, it]) => !(it.kind === 'slab' && footprint > 0 && area(it) > footprint * OVERSIZED_SLAB_FACTOR)).map(([id]) => id);
}
