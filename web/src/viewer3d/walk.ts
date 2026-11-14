import { Box3, DoubleSide, Euler, Mesh, MeshBasicMaterial, Raycaster, Vector3, type PerspectiveCamera, type Object3D } from 'three';
import type { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { cutawayStoreys } from './cutaway';
import { storeyName, type LoadedScene } from './scene';

export const WALK_EYE_HEIGHT_M = 1.6;
export const WALK_RADIUS_M = 0.3;
const SPEED_M_S = 2;

export interface WalkState {
  active: boolean;
  eye_height_m: number;
  storey: string | null;
  position: [number, number, number];
}

function visible(object: Object3D): boolean {
  for (let node: Object3D | null = object; node; node = node.parent) if (!node.visible) return false;
  return true;
}

/** Collision proxies share geometry, never render, and see both sides of walls.
 * Source nodes retain their visibility, materials and batching/picking layers. */
export function createWalkWorld(scene: LoadedScene) {
  scene.root.updateWorldMatrix(true, true);
  const material = new MeshBasicMaterial({ side: DoubleSide });
  const walls: { source: Mesh; proxy: Mesh; bounds: Box3 }[] = [];
  const doors: Box3[] = [];
  const boxes = new Map<string, Box3>();
  for (const [id, item] of Object.entries(scene.manifest.items)) {
    const source = scene.items.get(id);
    const bounds = item.bbox_m ? new Box3(new Vector3(...item.bbox_m[0]), new Vector3(...item.bbox_m[1]))
      : source ? new Box3().setFromObject(source) : new Box3();
    if (!bounds.isEmpty()) boxes.set(id, bounds);
    const kind = item.kind.toLowerCase();
    if (kind === 'door') doors.push(bounds);
    if (kind !== 'wall' && !/^ifcwall/i.test(scene.elements?.get(id)?.ifc_class ?? '')) continue;
    source?.traverse((object) => {
      if (!(object as Mesh).isMesh) return;
      const mesh = object as Mesh;
      const proxy = new Mesh(mesh.geometry, material);
      proxy.matrixWorld.copy(mesh.matrixWorld);
      walls.push({ source: mesh, proxy, bounds: new Box3().setFromObject(mesh) });
    });
  }
  const storeys = cutawayStoreys(scene.manifest);
  const ray = new Raycaster();
  const hitPoint = new Vector3();
  const forward = new Vector3();
  const origin = new Vector3();
  const side = new Vector3();

  function floor(name: string | null): number {
    const elevation = storeys.find((entry) => entry.name === name)?.elevation_m;
    if (elevation !== undefined) return elevation;
    const rooms = [...boxes].filter(([id]) => scene.manifest.items[id].kind === 'room'
      && storeyName(scene.manifest.items[id].storey) === name);
    return rooms.length ? Math.min(...rooms.map(([, box]) => box.min.y)) : 0;
  }

  function bounds(name: string | null): Box3 {
    const result = new Box3();
    for (const [id, box] of boxes) {
      const item = scene.manifest.items[id];
      if (storeyName(item.storey) === name && ['wall', 'room', 'door', 'window'].includes(item.kind)) result.union(box);
    }
    if (result.isEmpty()) for (const box of boxes.values()) result.union(box);
    return result;
  }

  function hitWall(start: Vector3, direction: Vector3, distance: number): boolean {
    ray.set(start, direction);
    ray.near = 0;
    ray.far = distance;
    for (const wall of walls) {
      if (!visible(wall.source) || !ray.ray.intersectsBox(wall.bounds)) continue;
      for (const hit of ray.intersectObject(wall.proxy, false)) {
        hitPoint.copy(hit.point);
        // Doors are passages even when an exporter leaves wall infill there.
        if (!doors.some((door) => door.containsPoint(hitPoint))) return true;
      }
    }
    return false;
  }

  function clear(position: Vector3): boolean {
    // Probe the body at ankle, torso and eye height, including wall back faces.
    for (const height of [0.35, 1, WALK_EYE_HEIGHT_M]) {
      origin.copy(position); origin.y += height - WALK_EYE_HEIGHT_M;
      if (!doors.some((door) => door.containsPoint(origin))) {
        // A thick wall can enclose a centroid farther than one radius from a
        // surface. Parity handles that case without filling doorway bboxes.
        ray.set(origin, new Vector3(0.917, 0, 0.399).normalize()); ray.far = Infinity;
        for (const wall of walls) {
          if (!visible(wall.source) || !wall.bounds.containsPoint(origin)) continue;
          const hits = ray.intersectObject(wall.proxy, false);
          const distances = hits.map((hit) => hit.distance).filter((distance, index, all) =>
            distance > 1e-7 && (index === 0 || Math.abs(distance - all[index - 1]) > 1e-6));
          if (distances.length % 2 === 1) return false;
        }
      }
      for (let index = 0; index < 16; index++) {
        const angle = index * Math.PI / 8;
        forward.set(Math.sin(angle), 0, Math.cos(angle));
        if (hitWall(origin, forward, WALK_RADIUS_M)) return false;
      }
    }
    return true;
  }

  function canMove(from: Vector3, to: Vector3, name: string | null): boolean {
    const box = bounds(name);
    if (!box.isEmpty() && (to.x < box.min.x + WALK_RADIUS_M || to.x > box.max.x - WALK_RADIUS_M
      || to.z < box.min.z + WALK_RADIUS_M || to.z > box.max.z - WALK_RADIUS_M)) return false;
    forward.subVectors(to, from).setY(0);
    const distance = forward.length();
    if (distance === 0) return true;
    forward.divideScalar(distance);
    side.set(-forward.z, 0, forward.x);
    // Sweep a 0.3 m body along the whole step, including its leading edge.
    for (const height of [0.35, 1, WALK_EYE_HEIGHT_M]) {
      for (const fraction of [-1, -0.75, -0.5, -0.25, 0, 0.25, 0.5, 0.75, 1]) {
        const offset = fraction * WALK_RADIUS_M;
        origin.copy(from).addScaledVector(side, offset);
        origin.y += height - WALK_EYE_HEIGHT_M;
        if (hitWall(origin, forward, distance + Math.sqrt(Math.max(0, WALK_RADIUS_M ** 2 - offset ** 2)))) return false;
      }
    }
    return true;
  }

  function start(name: string | null, targetId?: string | null): Vector3 | null {
    const box = bounds(name);
    const eye = floor(name) + WALK_EYE_HEIGHT_M;
    const target = targetId ? boxes.get(targetId)?.getCenter(new Vector3()).setY(eye) : undefined;
    const rooms = [...boxes].filter(([id]) => scene.manifest.items[id].kind === 'room'
      && storeyName(scene.manifest.items[id].storey) === name);
    rooms.sort((a, b) => {
      if (target) return a[1].distanceToPoint(target) - b[1].distanceToPoint(target);
      const area = (box: Box3) => (box.max.x - box.min.x) * (box.max.z - box.min.z);
      return area(b[1]) - area(a[1]);
    });
    function suitable(point: Vector3): boolean {
      return !box.isEmpty() && point.x >= box.min.x + WALK_RADIUS_M && point.x <= box.max.x - WALK_RADIUS_M
        && point.z >= box.min.z + WALK_RADIUS_M && point.z <= box.max.z - WALK_RADIUS_M && clear(point);
    }
    if (target && suitable(target)) return target;
    // First choice is the largest room's centroid (or the room nearest the answer).
    for (const [, room] of rooms) {
      const center = room.getCenter(new Vector3()).setY(eye);
      if (suitable(center)) return center;
      // Concave rooms and wall targets can put the bbox centre in a wall.
      for (const x of [0.25, 0.75]) for (const z of [0.25, 0.75]) {
        const point = new Vector3(room.min.x + (room.max.x - room.min.x) * x, eye,
          room.min.z + (room.max.z - room.min.z) * z);
        if (suitable(point)) return point;
      }
    }
    // Roofless plans may not contain room objects. Search their interior bounds.
    for (const x of [0.5, 0.25, 0.75, 0.1, 0.9]) for (const z of [0.5, 0.25, 0.75, 0.1, 0.9]) {
      const point = new Vector3(box.min.x + (box.max.x - box.min.x) * x, eye,
        box.min.z + (box.max.z - box.min.z) * z);
      if (suitable(point)) return point;
    }
    return null;
  }

  return { storeys, floor, bounds, start, clear, canMove, dispose: () => material.dispose() };
}

export function createWalkController(canvas: HTMLCanvasElement, camera: PerspectiveCamera, controls: OrbitControls,
  options: { getScene(): LoadedScene | null; getStorey(): string | null; setStorey(name: string | null): void;
    getTarget(): string | null; onChange(state: WalkState): void }) {
  let world: ReturnType<typeof createWalkWorld> | null = null;
  let active = false;
  let storey: string | null = null;
  let saved: { position: Vector3; quaternion: typeof camera.quaternion; target: Vector3;
    near: number; far: number; enabled: boolean; damping: boolean } | null = null;
  let yaw = 0, pitch = 0;
  const keys = new Set<string>();
  const stick = { x: 0, y: 0 };
  let drag: { id: number; x: number; y: number } | null = null;
  const rotation = new Euler(0, 0, 0, 'YXZ');
  const next = new Vector3();
  const movement = new Vector3();
  const state = (): WalkState => ({ active, eye_height_m: WALK_EYE_HEIGHT_M, storey, position: camera.position.toArray() });
  const notify = () => options.onChange(state());
  const look = () => { camera.quaternion.setFromEuler(rotation.set(pitch, yaw, 0)); camera.updateMatrixWorld(); };
  const resetInput = () => { keys.clear(); stick.x = stick.y = 0; drag = null; };

  function exit() {
    if (!active) return;
    active = false;
    resetInput();
    if (saved) {
      camera.position.copy(saved.position);
      camera.quaternion.copy(saved.quaternion);
      camera.near = saved.near; camera.far = saved.far; camera.updateProjectionMatrix();
      controls.target.copy(saved.target);
      controls.enabled = saved.enabled; controls.enableDamping = saved.damping;
    }
    world?.dispose(); world = null; saved = null;
    notify();
  }

  function enter(): boolean {
    const scene = options.getScene();
    if (!scene || active) return active;
    world = createWalkWorld(scene);
    const target = options.getTarget();
    storey = target ? storeyName(scene.manifest.items[target]?.storey ?? null) : options.getStorey();
    storey ??= world.storeys.find((entry) => (entry.elevation_m ?? -1) >= 0)?.name ?? world.storeys[0]?.name ?? null;
    const position = world.start(storey, target);
    if (!position) { world.dispose(); world = null; return false; }
    saved = { position: camera.position.clone(), quaternion: camera.quaternion.clone(), target: controls.target.clone(),
      near: camera.near, far: camera.far, enabled: controls.enabled, damping: controls.enableDamping };
    // Drain any residual orbit damping before disabling it for first person.
    controls.enableDamping = false; controls.update(); controls.enabled = false;
    camera.near = 0.05; camera.updateProjectionMatrix();
    options.setStorey(storey);
    camera.position.copy(position);
    yaw = pitch = 0; look();
    resetInput(); active = true;
    canvas.focus({ preventScroll: true });
    notify();
    return true;
  }

  function syncStorey() {
    if (!active || !world || storey === options.getStorey()) return;
    const name = options.getStorey();
    if (name === null) return;
    const position = world.start(name);
    if (!position) { exit(); return; }
    storey = name; camera.position.copy(position); resetInput(); look(); notify();
  }

  function keydown(event: KeyboardEvent) {
    if (!active || (document.activeElement !== canvas && event.code !== 'Escape')) return;
    if (event.code === 'Escape') {
      event.preventDefault(); event.stopImmediatePropagation(); exit(); return;
    }
    if (['KeyQ', 'KeyE', 'PageUp', 'PageDown'].includes(event.code)) {
      event.preventDefault();
      if (!event.repeat && world) {
        const index = world.storeys.findIndex((entry) => entry.name === storey);
        const direction = event.code === 'KeyE' || event.code === 'PageUp' ? 1 : -1;
        const next = world.storeys[index + direction];
        if (next) options.setStorey(next.name);
      }
      return;
    }
    if (['KeyW', 'KeyA', 'KeyS', 'KeyD', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(event.code)) {
      event.preventDefault(); keys.add(event.code);
    }
  }
  const keyup = (event: KeyboardEvent) => { keys.delete(event.code); };
  function pointerdown(event: PointerEvent) {
    if (!active || drag || event.button !== 0) return;
    canvas.focus({ preventScroll: true });
    drag = { id: event.pointerId, x: event.clientX, y: event.clientY };
    canvas.setPointerCapture(event.pointerId);
  }
  function pointermove(event: PointerEvent) {
    if (!active || !drag || drag.id !== event.pointerId) return;
    yaw -= (event.clientX - drag.x) * 0.004;
    pitch = Math.max(-Math.PI * 0.47, Math.min(Math.PI * 0.47, pitch - (event.clientY - drag.y) * 0.004));
    drag.x = event.clientX; drag.y = event.clientY; look();
  }
  const pointerup = (event: PointerEvent) => { if (drag?.id === event.pointerId) drag = null; };
  const blur = () => resetInput();
  const visibility = () => { if (document.hidden) resetInput(); };
  window.addEventListener('keydown', keydown, true);
  window.addEventListener('keyup', keyup);
  window.addEventListener('blur', blur);
  canvas.addEventListener('blur', blur);
  document.addEventListener('visibilitychange', visibility);
  canvas.addEventListener('pointerdown', pointerdown);
  canvas.addEventListener('pointermove', pointermove);
  canvas.addEventListener('pointerup', pointerup);
  canvas.addEventListener('pointercancel', pointerup);
  canvas.addEventListener('lostpointercapture', pointerup);

  return {
    state, enter, exit, syncStorey,
    joystick(x: number, y: number) { stick.x = x; stick.y = y; },
    update(dt: number) {
      if (!active || !world) return;
      const x = Number(keys.has('KeyD') || keys.has('ArrowRight')) - Number(keys.has('KeyA') || keys.has('ArrowLeft')) + stick.x;
      const z = Number(keys.has('KeyS') || keys.has('ArrowDown')) - Number(keys.has('KeyW') || keys.has('ArrowUp')) + stick.y;
      movement.set(x, 0, z);
      if (movement.lengthSq() === 0) return;
      if (movement.lengthSq() > 1) movement.normalize();
      movement.applyAxisAngle(camera.up, yaw).multiplyScalar(SPEED_M_S * Math.min(dt, 0.05));
      // Substeps prevent thin-wall tunnelling after a slow frame.
      const steps = Math.max(1, Math.ceil(movement.length() / 0.08));
      movement.divideScalar(steps);
      for (let step = 0; step < steps; step++) {
        next.copy(camera.position).add(movement);
        if (world.canMove(camera.position, next, storey)) camera.position.copy(next);
        else for (const axis of ['x', 'z'] as const) {
          next.copy(camera.position); next[axis] += movement[axis];
          if (world.canMove(camera.position, next, storey)) camera.position.copy(next);
        }
      }
      camera.updateMatrixWorld();
    },
    dispose() {
      exit();
      window.removeEventListener('keydown', keydown, true);
      window.removeEventListener('keyup', keyup);
      window.removeEventListener('blur', blur);
      canvas.removeEventListener('blur', blur);
      document.removeEventListener('visibilitychange', visibility);
      canvas.removeEventListener('pointerdown', pointerdown);
      canvas.removeEventListener('pointermove', pointermove);
      canvas.removeEventListener('pointerup', pointerup);
      canvas.removeEventListener('pointercancel', pointerup);
      canvas.removeEventListener('lostpointercapture', pointerup);
    },
  };
}
