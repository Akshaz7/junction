import {
  AmbientLight, Box3, Color, DirectionalLight, PerspectiveCamera,
  Raycaster, Scene, Sphere, Vector2, Vector3, WebGLRenderer,
} from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { CSS2DObject, CSS2DRenderer } from 'three/examples/jsm/renderers/CSS2DRenderer.js';
import {
  createHighlightController, itemBounds, readHighlightColor, type HighlightOptions, type HighlightState,
} from './highlight';
import {
  disposeScene, itemIdForObject, loadScene, type LoadedScene,
} from './scene';
import { createCutawayController, type CutawayState } from './cutaway';
import { createRiseAnimation, scheduleRiseTransitions, type RisePhase, type RiseState } from './rise';

export interface Viewer {
  readonly renderer: WebGLRenderer;
  readonly camera: PerspectiveCamera;
  readonly controls: OrbitControls;
  readonly scene: LoadedScene | null;
  loadScene(url: string | URL): Promise<LoadedScene>;
  /** Transfers ownership; replaced scenes and the active scene are disposed by the viewer. */
  setScene(scene: LoadedScene): void;
  setStorey(name: string | null): void;
  setShowRoof(show: boolean): void;
  getCutawayState(): CutawayState;
  onCutawayChange(callback: (state: CutawayState) => void): () => void;
  highlight(item_ids: readonly string[], options?: HighlightOptions): void;
  clearHighlight(): void;
  getHighlightState(): HighlightState;
  onHighlightChange(callback: (state: HighlightState) => void): () => void;
  /** Show the flat plan/top-down IFC view, then raise the architectural items. */
  visualise(onStateChange?: (state: RiseState) => void): void;
  /** Coordinates are viewport client pixels, as in PointerEvent.clientX/clientY. */
  pick(x: number, y: number): string | null;
  resize(): void;
  dispose(): void;
}

export function createViewer(canvas: HTMLCanvasElement): Viewer {
  const renderer = new WebGLRenderer({ canvas, antialias: true, alpha: false });
  const labelRenderer = new CSS2DRenderer();
  labelRenderer.domElement.className = 'viewer3d-label-layer';
  Object.assign(labelRenderer.domElement.style, { position: 'absolute', pointerEvents: 'none', top: '0', left: '0' });
  canvas.parentElement?.append(labelRenderer.domElement);
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
  let cutaway: ReturnType<typeof createCutawayController> | null = null;
  const cutawayListeners = new Set<(state: CutawayState) => void>();
  function notifyCutaway(): void {
    if (cutaway) for (const listener of cutawayListeners) listener(cutaway.getState());
  }
  let disposed = false;
  let loadVersion = 0;
  let highlights: ReturnType<typeof createHighlightController> | null = null;
  const highlightListeners = new Set<(state: HighlightState) => void>();
  const labels: CSS2DObject[] = [];
  let flight: { start: number; from: Vector3; to: Vector3; targetFrom: Vector3; targetTo: Vector3 } | null = null;
  let rise: {
    animation: ReturnType<typeof createRiseAnimation>; from: Vector3; to: Vector3;
    phase: RisePhase; onStateChange?: (state: RiseState) => void; cancelTransitions: () => void;
  } | null = null;
  const raycaster = new Raycaster();
  const pointer = new Vector2();

  function resize(): void {
    if (disposed) return;
    const rect = canvas.getBoundingClientRect();
    const width = Math.max(1, rect.width);
    const height = Math.max(1, rect.height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(width, height, false);
    labelRenderer.setSize(width, height);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  }

  function clearHighlight(): void {
    flight = null;
    highlights?.clearHighlight();
    for (const label of labels) {
      label.removeFromParent();
      label.element.remove();
    }
    labels.length = 0;
  }

  function flyTo(bounds: Box3): void {
    if (bounds.isEmpty()) return;
    const sphere = bounds.getBoundingSphere(new Sphere());
    const radius = Math.max(sphere.radius, 0.1);
    const halfFov = camera.fov * Math.PI / 360;
    const limitingFov = Math.min(halfFov, Math.atan(Math.tan(halfFov) * camera.aspect));
    const distance = radius / Math.sin(limitingFov) * 1.25;
    const direction = camera.position.clone().sub(controls.target).normalize();
    if (direction.lengthSq() === 0) direction.set(1, 0.8, 1).normalize();
    flight = {
      start: performance.now(), from: camera.position.clone(),
      to: sphere.center.clone().addScaledVector(direction, distance),
      targetFrom: controls.target.clone(), targetTo: sphere.center,
    };
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      camera.position.copy(flight.to);
      controls.target.copy(flight.targetTo);
      camera.lookAt(controls.target);
      flight = null;
    }
    camera.near = Math.min(camera.near, radius / 1000);
    camera.far = Math.max(camera.far, distance + radius * 10);
    camera.updateProjectionMatrix();
    controls.minDistance = Math.min(controls.minDistance, radius / 100);
    controls.maxDistance = Math.max(controls.maxDistance, distance * 5);
  }

  function highlight(ids: readonly string[], options: HighlightOptions = {}): void {
    clearHighlight();
    if (disposed || !active || !highlights) return;
    cutaway?.followHighlight(ids, options.cameraTargetItemId);
    notifyCutaway();
    // Compute labels using full geometry: a flat node has a singular world matrix.
    rise?.animation.restore();
    const accent = readHighlightColor(canvas);
    highlights.highlight(ids, options, accent);
    const state = highlights.getHighlightState();
    for (const id of state.highlighted) {
      const object = active.items.get(id)!;
      const bounds = itemBounds(active, [id]);
      if (bounds.isEmpty()) continue;
      const element = document.createElement('span');
      element.className = 'viewer3d-item-label';
      element.dataset.itemId = id;
      element.textContent = state.labels[id];
      element.setAttribute('aria-label', `Item ${state.labels[id]}: ${id}`);
      element.style.backgroundColor = accent.getStyle();
      const label = new CSS2DObject(element);
      const top = bounds.getCenter(new Vector3());
      top.y = bounds.max.y + Math.max(bounds.getSize(new Vector3()).length() * 0.04, 0.08);
      label.position.copy(object.worldToLocal(top));
      object.add(label);
      labels.push(label);
    }
    const target = options.cameraTargetItemId;
    if (rise) rise.animation.sample(performance.now());
    else flyTo(itemBounds(active, target && active.items.has(target) ? [target] : state.highlighted));
    notifyHighlight();
  }

  function notifyHighlight(): void {
    if (!highlights) return;
    for (const listener of highlightListeners) listener(highlights.getHighlightState());
  }

  function visualise(onStateChange?: (state: RiseState) => void): void {
    if (disposed || !active) return;
    rise?.cancelTransitions();
    rise?.animation.restore();
    rise = null;
    flight = null;
    fit(active);
    const to = camera.position.clone();
    const distance = to.distanceTo(controls.target);
    // A tiny Z offset avoids the camera-up singularity at an exact overhead view.
    const from = controls.target.clone().add(new Vector3(0, distance, distance * 0.001));
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const animation = createRiseAnimation(active, performance.now(), reducedMotion);
    const state = animation.sample(performance.now());
    if (!reducedMotion) {
      rise = { animation, from, to, phase: state.phase, onStateChange,
        cancelTransitions: scheduleRiseTransitions(sampleRise) };
      camera.position.copy(from);
      camera.lookAt(controls.target);
    }
    onStateChange?.(state);
  }

  function sampleRise(): void {
    const current = rise;
    if (!current || disposed) return;
    const state = current.animation.sample(performance.now());
    camera.position.lerpVectors(current.from, current.to, state.progress);
    camera.lookAt(controls.target);
    if (state.phase !== current.phase) {
      current.phase = state.phase;
      current.onStateChange?.(state);
    }
    if (state.phase === 'done') {
      current.cancelTransitions();
      rise = null;
    }
  }

  // Direct orbit/zoom input takes over from a camera flight.
  controls.addEventListener('start', () => {
    flight = null;
    // User input takes over both the camera and the animation.
    if (rise) {
      const previous = rise;
      rise = null;
      previous.cancelTransitions();
      previous.animation.restore();
      previous.onStateChange?.({ phase: 'done', progress: 1 });
    }
  });

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
    rise?.cancelTransitions();
    rise?.animation.restore();
    rise = null;
    clearHighlight();
    if (active) {
      world.remove(active.root);
      disposeScene(active);
    }
    active = scene;
    cutaway = createCutawayController(scene);
    highlights = createHighlightController(scene);
    world.add(scene.root);
    fit(scene);
    notifyCutaway();
  }

  const observer = new ResizeObserver(resize);
  observer.observe(canvas);
  window.addEventListener('resize', resize);
  resize();
  let frame = 0;
  function render(): void {
    if (disposed) return;
    controls.update();
    sampleRise();
    if (flight) {
      const progress = Math.min(1, (performance.now() - flight.start) / 600);
      const eased = progress * progress * (3 - 2 * progress);
      controls.target.lerpVectors(flight.targetFrom, flight.targetTo, eased);
      camera.position.lerpVectors(flight.from, flight.to, eased);
      camera.lookAt(controls.target);
      if (progress === 1) flight = null;
    }
    renderer.render(world, camera);
    labelRenderer.render(world, camera);
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
      cutaway?.setStorey(name);
      notifyCutaway();
    },
    setShowRoof(show) { cutaway?.setShowRoof(show); notifyCutaway(); },
    getCutawayState() { return cutaway?.getState() ?? { activeStorey: null, showRoof: false, hiddenCount: 0 }; },
    onCutawayChange(callback) {
      cutawayListeners.add(callback);
      return () => { cutawayListeners.delete(callback); };
    },
    highlight,
    clearHighlight() { clearHighlight(); notifyHighlight(); },
    getHighlightState() {
      return highlights?.getHighlightState() ?? { highlighted: [], dimmed: 0, labels: {} };
    },
    onHighlightChange(callback) {
      highlightListeners.add(callback);
      return () => { highlightListeners.delete(callback); };
    },
    visualise,
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
      highlightListeners.clear();
      cutawayListeners.clear();
      loadVersion++;
      cancelAnimationFrame(frame);
      observer.disconnect();
      window.removeEventListener('resize', resize);
      controls.dispose();
      rise?.cancelTransitions();
      rise?.animation.restore();
      rise = null;
      clearHighlight();
      labelRenderer.domElement.remove();
      if (active) {
        world.remove(active.root);
        disposeScene(active);
        active = null;
      }
      highlights = null;
      renderer.dispose();
    },
  };
}
