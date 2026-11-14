import {
  AmbientLight, Box3, Color, DirectionalLight, PerspectiveCamera,
  Raycaster, Scene, Sphere, Vector2, Vector3, WebGLRenderer,
} from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import {
  disposeScene, itemIdForObject, loadScene, setStorey, type LoadedScene,
} from './scene';

export interface Viewer {
  readonly renderer: WebGLRenderer;
  readonly camera: PerspectiveCamera;
  readonly controls: OrbitControls;
  readonly scene: LoadedScene | null;
  loadScene(url: string | URL): Promise<LoadedScene>;
  /** Transfers ownership; replaced scenes and the active scene are disposed by the viewer. */
  setScene(scene: LoadedScene): void;
  setStorey(name: string | null): void;
  /** Coordinates are viewport client pixels, as in PointerEvent.clientX/clientY. */
  pick(x: number, y: number): string | null;
  resize(): void;
  dispose(): void;
}

export function createViewer(canvas: HTMLCanvasElement): Viewer {
  const renderer = new WebGLRenderer({ canvas, antialias: true, alpha: false });
  const world = new Scene();
  world.background = new Color('#f4f3ef');
  const camera = new PerspectiveCamera(45, 1, 0.01, 10000);
  camera.position.set(12, 10, 12);
  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true;
  world.add(new AmbientLight(0xffffff, 1.5));
  const light = new DirectionalLight(0xffffff, 2.5);
  light.position.set(8, 16, 10);
  world.add(light);

  let active: LoadedScene | null = null;
  let storey: string | null = null;
  let disposed = false;
  let loadVersion = 0;
  const raycaster = new Raycaster();
  const pointer = new Vector2();

  function resize(): void {
    if (disposed) return;
    const rect = canvas.getBoundingClientRect();
    const width = Math.max(1, rect.width);
    const height = Math.max(1, rect.height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  }

  function fit(scene: LoadedScene): void {
    scene.root.updateWorldMatrix(true, true);
    const bounds = new Box3().setFromObject(scene.root);
    if (bounds.isEmpty()) return;
    const sphere = bounds.getBoundingSphere(new Sphere());
    const radius = Math.max(sphere.radius, 0.1);
    const verticalFov = camera.fov * Math.PI / 360;
    const limitingFov = Math.min(verticalFov, Math.atan(Math.tan(verticalFov) * camera.aspect));
    const distance = radius / Math.sin(limitingFov) * 1.15;
    controls.target.copy(sphere.center);
    camera.position.copy(sphere.center).add(new Vector3(1, 0.8, 1).normalize().multiplyScalar(distance));
    camera.near = Math.max(radius / 1000, 0.001);
    camera.far = Math.max(distance + radius * 10, 100);
    camera.updateProjectionMatrix();
    controls.maxDistance = distance * 5;
    controls.minDistance = radius / 100;
    controls.update();
    controls.saveState();
  }

  function attach(scene: LoadedScene): void {
    if (active === scene) return;
    if (active) {
      world.remove(active.root);
      disposeScene(active);
    }
    active = scene;
    world.add(scene.root);
    fit(scene);
    setStorey(scene, storey);
  }

  const observer = new ResizeObserver(resize);
  observer.observe(canvas);
  window.addEventListener('resize', resize);
  resize();
  let frame = 0;
  function render(): void {
    if (disposed) return;
    controls.update();
    renderer.render(world, camera);
    frame = requestAnimationFrame(render);
  }
  render();

  return {
    renderer, camera, controls,
    get scene() { return active; },
    async loadScene(url) {
      if (disposed) throw new Error('Viewer has been disposed');
      const version = ++loadVersion;
      const loaded = await loadScene(url);
      if (disposed || version !== loadVersion) {
        disposeScene(loaded);
        throw new Error('Scene load was superseded or viewer disposed');
      }
      attach(loaded);
      return loaded;
    },
    setScene(scene) {
      if (disposed) throw new Error('Viewer has been disposed');
      loadVersion++;
      attach(scene);
    },
    setStorey(name) {
      storey = name;
      if (active) setStorey(active, name);
    },
    pick(x, y) {
      if (disposed || !active) return null;
      const rect = canvas.getBoundingClientRect();
      if (!rect.width || !rect.height || x < rect.left || x > rect.right || y < rect.top || y > rect.bottom) return null;
      pointer.set((x - rect.left) / rect.width * 2 - 1, -(y - rect.top) / rect.height * 2 + 1);
      camera.updateWorldMatrix(true, false);
      active.root.updateWorldMatrix(true, true);
      raycaster.setFromCamera(pointer, camera);
      for (const hit of raycaster.intersectObject(active.root, true)) {
        const id = itemIdForObject(active, hit.object);
        if (id !== null) return id;
      }
      return null;
    },
    resize,
    dispose() {
      if (disposed) return;
      disposed = true;
      loadVersion++;
      cancelAnimationFrame(frame);
      observer.disconnect();
      window.removeEventListener('resize', resize);
      controls.dispose();
      if (active) {
        world.remove(active.root);
        disposeScene(active);
        active = null;
      }
      renderer.dispose();
    },
  };
}
