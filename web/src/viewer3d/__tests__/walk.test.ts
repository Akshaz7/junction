// @vitest-environment node
import { afterEach, describe, expect, it, vi } from 'vitest';
import { BoxGeometry, Group, Mesh, MeshBasicMaterial, PerspectiveCamera, Vector3 } from 'three';
import type { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { createScene, type SceneManifest } from '../scene';
import { createWalkController, createWalkWorld } from '../walk';

function fixture() {
  const root = new Group();
  const manifest: SceneManifest = {
    doc_id: 'generated-for-demo', glb: 'scene.glb', usdz: null, units: 'm', up: 'Y', origin_offset_m: [0, 0, 0],
    storeys: [{ name: 'Ground', elevation_m: 0 }, { name: 'Upper', elevation_m: 3 }], items: {},
  };
  function add(id: string, kind: string, size: [number, number, number], position: [number, number, number], storey = 'Ground') {
    const mesh = new Mesh(new BoxGeometry(...size), new MeshBasicMaterial());
    mesh.name = id; mesh.position.set(...position); root.add(mesh);
    manifest.items[id] = { node: id, usd_name: id, kind, storey,
      bbox_m: [position.map((v, i) => v - size[i] / 2) as [number, number, number],
        position.map((v, i) => v + size[i] / 2) as [number, number, number]] };
    return mesh;
  }
  add('room', 'room', [10, 2.7, 10], [0, 1.35, 0]);
  add('small-room', 'room', [2, 2.7, 2], [-3, 1.35, 3]);
  add('upper-room', 'room', [10, 2.7, 10], [0, 4.35, 0], 'Upper');
  const wall = add('wall', 'wall', [10, 2.7, 0.1], [0, 1.35, -2]);
  const door = add('door', 'door', [1, 2.1, 0.2], [2, 1.05, -2]);
  // Simulate T-07 originals being moved off the render layer.
  wall.layers.set(31);
  const scene = createScene(manifest, { scene: root, parser: { associations: new Map(), json: {} } } as Parameters<typeof createScene>[1]);
  return { scene, wall, door };
}

describe('walk geometry (generated for demo)', () => {
  it('starts in the largest ground room at eye height and uses target/floor metadata', () => {
    const { scene } = fixture();
    const world = createWalkWorld(scene);
    expect(world.start('Ground')?.toArray()).toEqual([0, 1.6, 0]);
    expect(world.start('Ground', 'small-room')?.toArray()).toEqual([-3, 1.6, 3]);
    expect(world.start('Upper', 'upper-room')?.toArray()).toEqual([0, 4.6, 0]);
    // A wall's centroid is unsafe, so prefer a nearby room interior.
    expect(world.clear(world.start('Ground', 'wall')!)).toBe(true);
    world.dispose();
  });

  it('sweeps a 0.3 m body against thin walls from both sides and prevents tunnelling', () => {
    const { scene, wall } = fixture();
    const originalMaterial = wall.material;
    const originalLayers = wall.layers.mask;
    const world = createWalkWorld(scene);
    const p = (x: number, z: number) => new Vector3(x, 1.6, z);
    expect(world.canMove(p(0, 0), p(0, -1.6), 'Ground')).toBe(true);
    expect(world.canMove(p(0, -1.6), p(0, -1.7), 'Ground')).toBe(false);
    expect(world.canMove(p(0, 0), p(0, -4), 'Ground')).toBe(false);
    expect(world.canMove(p(0, -4), p(0, 0), 'Ground')).toBe(false);
    expect(world.clear(p(0, -1.8))).toBe(false);
    expect(world.canMove(p(0, 0), p(5, 0), 'Ground')).toBe(false);
    expect(wall.material).toBe(originalMaterial);
    expect(wall.layers.mask).toBe(originalLayers);
    world.dispose();
  });

  it('allows doors and hidden walls, and immediately respects restored walls', () => {
    const { scene, wall } = fixture();
    const world = createWalkWorld(scene);
    expect(world.canMove(new Vector3(2, 1.6, 0), new Vector3(2, 1.6, -4), 'Ground')).toBe(true);
    wall.visible = false;
    expect(world.canMove(new Vector3(0, 1.6, 0), new Vector3(0, 1.6, -4), 'Ground')).toBe(true);
    wall.visible = true;
    expect(world.canMove(new Vector3(0, 1.6, 0), new Vector3(0, 1.6, -4), 'Ground')).toBe(false);
    world.dispose();
  });

  it('uses real wall surfaces rather than treating a doorway bounding box as solid', () => {
    const { scene, wall } = fixture();
    wall.visible = false;
    const arch = new Group(); arch.name = 'open-wall';
    for (const x of [-3, 3]) {
      const mesh = new Mesh(new BoxGeometry(4, 2.7, 0.2), new MeshBasicMaterial());
      mesh.position.set(x, 1.35, -2); arch.add(mesh);
    }
    scene.root.add(arch); scene.items.set('open-wall', arch);
    scene.manifest.items['open-wall'] = { node: 'open-wall', usd_name: 'open-wall', kind: 'wall', storey: 'Ground',
      bbox_m: [[-5, 0, -2.1], [5, 2.7, -1.9]] };
    const world = createWalkWorld(scene);
    expect(world.canMove(new Vector3(0, 1.6, 0), new Vector3(0, 1.6, -4), 'Ground')).toBe(true);
    expect(world.canMove(new Vector3(0.8, 1.6, 0), new Vector3(0.8, 1.6, -4), 'Ground')).toBe(false);
    world.dispose();
  });
});

afterEach(() => vi.unstubAllGlobals());

it('walk controls move, look, change floors, handle a second touch, and restore the orbit camera on Esc', () => {
  const win = new EventTarget();
  const doc = Object.assign(new EventTarget(), { activeElement: null as EventTarget | null, hidden: false });
  const canvas = Object.assign(new EventTarget(), {
    focus() { doc.activeElement = canvas; }, setPointerCapture() {},
  });
  vi.stubGlobal('window', win); vi.stubGlobal('document', doc);
  const camera = new PerspectiveCamera(45, 1, 0.02, 1000);
  camera.position.set(15, 12, 15); camera.lookAt(0, 0, 0);
  const position = camera.position.clone(), quaternion = camera.quaternion.clone();
  const controls = { target: new Vector3(0, 1, 0), enabled: true, enableDamping: true, update() {} };
  const { scene } = fixture();
  let storey: string | null = 'Ground';
  const controller = createWalkController(canvas as unknown as HTMLCanvasElement, camera, controls as OrbitControls, {
    getScene: () => scene, getStorey: () => storey, getTarget: () => null,
    setStorey(name) { storey = name; controller.syncStorey(); }, onChange() {},
  });
  const key = (type: string, code: string) => win.dispatchEvent(Object.assign(new Event(type, { cancelable: true }), { code }));
  expect(controller.enter()).toBe(true);
  expect(controls.enabled).toBe(false);
  key('keydown', 'KeyW');
  for (let i = 0; i < 20; i++) controller.update(0.05);
  key('keyup', 'KeyW');
  expect(camera.position.z).toBeLessThan(-1);
  expect(camera.position.z).toBeGreaterThan(-1.66);
  expect(camera.position.y).toBe(1.6);
  const beforeLook = camera.quaternion.clone();
  canvas.dispatchEvent(Object.assign(new Event('pointerdown'), { pointerId: 2, isPrimary: false, button: 0, clientX: 0, clientY: 0 }));
  canvas.dispatchEvent(Object.assign(new Event('pointermove'), { pointerId: 2, clientX: 100, clientY: 25 }));
  expect(camera.quaternion.equals(beforeLook)).toBe(false);
  key('keydown', 'PageUp');
  expect(controller.state().storey).toBe('Upper');
  expect(camera.position.y).toBe(4.6);
  controller.joystick(1, 0); controller.update(0.05);
  expect(camera.position.x).not.toBe(0);
  win.dispatchEvent(new Event('blur'));
  const stopped = camera.position.clone(); controller.update(0.05);
  expect(camera.position.equals(stopped)).toBe(true);
  key('keydown', 'KeyQ');
  expect(camera.position.y).toBe(1.6);
  key('keydown', 'Escape');
  expect(controller.state().active).toBe(false);
  expect(camera.position.equals(position)).toBe(true);
  expect(camera.quaternion.equals(quaternion)).toBe(true);
  expect(camera.near).toBe(0.02);
  expect(controls.target.toArray()).toEqual([0, 1, 0]);
  expect(controls.enabled).toBe(true);
  expect(controls.enableDamping).toBe(true);
  controller.dispose();
});
