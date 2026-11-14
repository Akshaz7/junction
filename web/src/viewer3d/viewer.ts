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
import { createLinkedHighlightController } from './linkedHighlight';
import { createRiseAnimation, scheduleRiseTransitions, type RisePhase, type RiseState } from './rise';
import { applyCommand, applyState, emptyCommandState, readCommandState, type SceneCommand, type SceneSnapshot, type CommandTestState } from './commands';
import { createCommandVisuals } from './commandVisuals';
import { createFrameProbe, type ViewerPerf } from './perf';
import { createRenderBatches, PICK_LAYER } from './renderBatches';
import { withAbort, type LoadProgress } from './loadGLTF';

export const SCENE_LOAD_BUDGET_MS = 60_000;

export interface Viewer {
  readonly renderer: WebGLRenderer;
  readonly camera: PerspectiveCamera;
  readonly controls: OrbitControls;
  readonly scene: LoadedScene | null;
  perf(): ViewerPerf;
  resetPerf(): void;
  loadScene(url: string | URL, options?: { onProgress?: (progress: LoadProgress) => void }): Promise<LoadedScene>;
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
  applyCommand(command: SceneCommand): void;
  applyState(snapshot: SceneSnapshot): void;
  getCommandState(): CommandTestState;
  onCommandChange(callback: (command: SceneCommand) => void): () => void;
  isApplyingCommand(): boolean;
  /** Local 2D/3D interaction layer, independent of answer/live highlights. */
  setLinkedItems(hovered: string | null, selected: string | null, labels?: Record<string, string>): void;
  getLinkedHighlightState(): HighlightState;
  /** Show the flat plan/top-down IFC view, then raise the architectural items. */
  visualise(onStateChange?: (state: RiseState) => void): void;
  /** Coordinates are viewport client pixels, as in PointerEvent.clientX/clientY. */
  pick(x: number, y: number): string | null;
  resize(): void;
  dispose(): void;
}

export function createViewer(canvas: HTMLCanvasElement): Viewer {
  const probe = createFrameProbe();
  const renderer = new WebGLRenderer({ canvas, antialias: true, alpha: false });
  renderer.shadowMap.enabled = false;
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
  // Populated on the first pointer interaction, never during model loading.
  let pickMeshes: Scene['children'] | null = null;
  let renderBatches: ReturnType<typeof createRenderBatches> | null = null;
  let batchesDirty = false;
  let cutaway: ReturnType<typeof createCutawayController> | null = null;
  const cutawayListeners = new Set<(state: CutawayState) => void>();
  function notifyCutaway(): void {
    batchesDirty = true;
    if (cutaway) for (const listener of cutawayListeners) listener(cutaway.getState());
  }
  let disposed = false;
  let loadVersion = 0;
  let pendingLoad: AbortController | null = null;
  let highlights: ReturnType<typeof createHighlightController> | null = null;
  let linkedHighlights: ReturnType<typeof createLinkedHighlightController> | null = null;
  let commandVisuals: ReturnType<typeof createCommandVisuals> | null = null;
  let commandState = emptyCommandState();
  let applyingCommand = false;
  const commandListeners = new Set<(command: SceneCommand) => void>();
  let linked = { hovered: null as string | null, selected: null as string | null, labels: {} as Record<string, string> };
  let linkedLabel: CSS2DObject | null = null;
  const highlightListeners = new Set<(state: HighlightState) => void>();
  const labels: CSS2DObject[] = [];
  let flight: { start: number; from: Vector3; to: Vector3; targetFrom: Vector3; targetTo: Vector3 } | null = null;
  let rise: {
    animation: ReturnType<typeof createRiseAnimation>; from: Vector3; to: Vector3;
    phase: RisePhase; onStateChange?: (state: RiseState) => void; cancelTransitions: () => void;
  } | null = null;
  const raycaster = new Raycaster();
  raycaster.layers.enable(PICK_LAYER);
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
    batchesDirty = true;
    commandVisuals?.clearMaterials();
    flight = null;
    clearLinkedVisuals();
    highlights?.clearHighlight();
    for (const label of labels) {
      label.removeFromParent();
      label.element.remove();
    }
    labels.length = 0;
  }

  function clearLinkedVisuals(): void {
    linkedHighlights?.clear();
    linkedLabel?.removeFromParent();
    linkedLabel?.element.remove();
    linkedLabel = null;
  }

  function getLinkedHighlightState(): HighlightState {
    const base = highlights?.getHighlightState() ?? { highlighted: [], dimmed: 0, labels: {} };
    const highlighted = [...new Set([...base.highlighted, linked.hovered, linked.selected]
      .filter((id): id is string => id !== null && !!active?.items.has(id)))];
    if (linked.selected && active?.items.has(linked.selected)) {
      base.labels[linked.selected] ??= linked.labels[linked.selected]
        ?? active.manifest.items[linked.selected].tag ?? linked.selected;
    }
    return { highlighted, dimmed: Math.max(0, base.dimmed - (highlighted.length - base.highlighted.length)), labels: base.labels };
  }

  function applyLinkedVisuals(): void {
    batchesDirty = true;
    commandVisuals?.clearMaterials();
    clearLinkedVisuals();
    if (disposed || !active) return;
    const accent = readHighlightColor(canvas);
    if (linked.hovered || linked.selected) ensureInteractionMaterials();
    linkedHighlights?.apply(linked.hovered, linked.selected, accent);
    commandVisuals?.rebuildMaterials();
    commandVisuals?.sample(performance.now());
    const id = linked.selected;
    if (!id || !active.items.has(id) || labels.some((label) => label.element.dataset.itemId === id)) return;
    // A selection can arrive while the plan is still flat. Position its label
    // in the full geometry frame before returning to the current rise phase.
    rise?.animation.restore();
    const bounds = itemBounds(active, [id]);
    if (bounds.isEmpty()) { rise?.animation.sample(performance.now()); return; }
    const element = document.createElement('span');
    const text = getLinkedHighlightState().labels[id];
    element.className = 'viewer3d-item-label';
    element.dataset.itemId = id;
    element.textContent = text;
    element.setAttribute('aria-label', `Item ${text}: ${id}`);
    element.style.backgroundColor = accent.getStyle();
    linkedLabel = new CSS2DObject(element);
    const top = bounds.getCenter(new Vector3());
    top.y = bounds.max.y + Math.max(bounds.getSize(new Vector3()).length() * 0.04, 0.08);
    const object = active.items.get(id)!;
    linkedLabel.position.copy(object.worldToLocal(top));
    object.add(linkedLabel);
    rise?.animation.sample(performance.now());
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
    if (ids.length) ensureInteractionMaterials();
    clearHighlight();
    if (disposed || !active || !highlights) return;
    cutaway?.followHighlight(ids, options.cameraTargetItemId);
    commandVisuals?.captureVisibility();
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
    applyLinkedVisuals();
    if (rise) rise.animation.sample(performance.now());
    else flyTo(itemBounds(active, target && active.items.has(target) ? [target] : state.highlighted));
    notifyHighlight();
  }

  function notifyHighlight(): void {
    batchesDirty = true;
    if (!highlights) return;
    for (const listener of highlightListeners) listener(highlights.getHighlightState());
  }

  function renderCommandState(): void {
    if (!active) return;
    ensureInteractionMaterials();
    const labels = Object.fromEntries(commandState.highlighted);
    applyingCommand = true;
    try {
      commandVisuals?.setState(commandState, performance.now(), window.matchMedia('(prefers-reduced-motion: reduce)').matches);
      highlight([...commandState.highlighted.keys()], { labels, dimOthers: commandState.isolated === null });
    } finally { applyingCommand = false; }
  }

  function visualise(onStateChange?: (state: RiseState) => void): void {
    if (disposed || !active) return;
    batchesDirty = true;
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
      batchesDirty = true;
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
    commandVisuals?.dispose();
    renderBatches?.dispose();
    renderBatches = null;
    if (active) {
      world.remove(active.root);
      disposeScene(active);
    }
    active = scene;
    pickMeshes = null;
    commandState = emptyCommandState();
    linked = { hovered: null, selected: null, labels: {} };
    cutaway = createCutawayController(scene);
    highlights = createHighlightController(scene);
    // Keep the source-material index lazy until the first highlight/selection.
    // It must be captured before any interaction replaces original materials.
    linkedHighlights = null;
    commandVisuals = createCommandVisuals(scene);
    world.add(scene.root);
    fit(scene);
    renderBatches = createRenderBatches(scene);
    world.add(renderBatches.root);
    notifyCutaway();
  }

  function ensureInteractionMaterials(): void {
    if (active && !linkedHighlights) linkedHighlights = createLinkedHighlightController(active);
  }

  const observer = new ResizeObserver(resize);
  observer.observe(canvas);
  window.addEventListener('resize', resize);
  resize();
  let frame = 0;
  function render(): void {
    if (disposed) return;
    controls.update();
    const wasRising = rise !== null;
    sampleRise();
    const fading = commandVisuals?.sample(performance.now());
    if (flight) {
      const progress = Math.min(1, (performance.now() - flight.start) / 600);
      const eased = progress * progress * (3 - 2 * progress);
      controls.target.lerpVectors(flight.targetFrom, flight.targetTo, eased);
      camera.position.lerpVectors(flight.from, flight.to, eased);
      camera.lookAt(controls.target);
      if (progress === 1) flight = null;
    }
    if (batchesDirty || wasRising || fading) {
      renderBatches?.sync();
      batchesDirty = false;
    }
    renderer.render(world, camera);
    if (labels.length || linkedLabel) labelRenderer.render(world, camera);
    probe.frame(performance.now(), active !== null);
    frame = requestAnimationFrame(render);
  }
  render();

  return {
    renderer, camera, controls,
    perf: () => probe.read(renderer.info.render.calls, renderer.info.render.triangles),
    resetPerf: () => probe.reset(),
    get scene() { return active; },
    async loadScene(url, options) {
      if (disposed) throw new Error('Viewer has been disposed');
      pendingLoad?.abort(new Error('Scene load superseded'));
      const controller = new AbortController();
      pendingLoad = controller;
      const timeout = setTimeout(() => controller.abort(new Error('3D model took too long to load (60 seconds). Try a smaller model.')),
        SCENE_LOAD_BUDGET_MS);
      const version = ++loadVersion;
      const loadStart = performance.now();
      try {
        const loaded = await withAbort(loadScene(url, { signal: controller.signal, onProgress: options?.onProgress }), controller.signal);
        if (disposed || version !== loadVersion || controller.signal.aborted) {
          disposeScene(loaded);
          controller.signal.throwIfAborted();
          throw new Error('Scene load was superseded or viewer disposed');
        }
        probe.beginLoad(loadStart);
        probe.reset();
        attach(loaded);
        return loaded;
      } finally {
        clearTimeout(timeout);
        if (pendingLoad === controller) pendingLoad = null;
      }
    },
    setScene(scene) {
      if (disposed) throw new Error('Viewer has been disposed');
      pendingLoad?.abort(new Error('Scene load superseded'));
      loadVersion++;
      pendingLoad = null;
      probe.beginLoad(performance.now());
      probe.reset();
      attach(scene);
    },
    setStorey(name) {
      cutaway?.setStorey(name);
      commandVisuals?.captureVisibility();
      commandVisuals?.sample(performance.now());
      notifyCutaway();
    },
    setShowRoof(show) {
      cutaway?.setShowRoof(show);
      commandVisuals?.captureVisibility();
      commandVisuals?.sample(performance.now());
      notifyCutaway();
    },
    getCutawayState() { return cutaway?.getState() ?? { activeStorey: null, showRoof: false, hiddenCount: 0 }; },
    onCutawayChange(callback) {
      cutawayListeners.add(callback);
      return () => { cutawayListeners.delete(callback); };
    },
    highlight,
    clearHighlight() { clearHighlight(); applyLinkedVisuals(); notifyHighlight(); },
    applyCommand(command) {
      if (!active || disposed) return;
      const resolved = command.op === 'highlight' || command.op === 'isolate'
        ? { ...command, labels: Object.fromEntries(command.item_ids.map((id) =>
          [id, command.labels?.[id] ?? active!.manifest.items[id]?.tag ?? id])) } : command;
      commandState = applyCommand(commandState, resolved);
      renderCommandState();
      for (const callback of commandListeners) callback(resolved);
    },
    applyState(snapshot) {
      if (!active || disposed) return;
      commandState = applyState({ ...snapshot, labels: Object.fromEntries(snapshot.highlighted.map((id) =>
        [id, snapshot.labels[id] ?? active!.manifest.items[id]?.tag ?? id])) });
      renderCommandState();
    },
    getCommandState() { return readCommandState(commandState); },
    onCommandChange(callback) { commandListeners.add(callback); return () => { commandListeners.delete(callback); }; },
    isApplyingCommand: () => applyingCommand,
    setLinkedItems(hovered, selected, labels = {}) {
      if (selected && selected !== linked.selected && active?.items.has(selected)) {
        cutaway?.followHighlight([selected]);
        commandVisuals?.captureVisibility();
        notifyCutaway();
      }
      linked = { hovered, selected, labels };
      applyLinkedVisuals();
    },
    getLinkedHighlightState,
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
      if (!pickMeshes) {
        pickMeshes = [];
        active.root.traverse((object) => {
          if (!(object as { isMesh?: boolean }).isMesh) return;
          // Include every storey so later cutaways do not invalidate the index.
          for (let owner: typeof object | null = object; owner; owner = owner.parent) {
            if (active!.itemIdsByObject.has(owner)) { pickMeshes!.push(object); break; }
          }
        });
      }
      const visibleMeshes = pickMeshes.filter((object) => itemIdForObject(active!, object) !== null);
      for (const hit of raycaster.intersectObjects(visibleMeshes, false)) {
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
      commandListeners.clear();
      cutawayListeners.clear();
      loadVersion++;
      pendingLoad?.abort(new Error('Viewer disposed'));
      pendingLoad = null;
      cancelAnimationFrame(frame);
      observer.disconnect();
      window.removeEventListener('resize', resize);
      controls.dispose();
      rise?.cancelTransitions();
      rise?.animation.restore();
      rise = null;
      clearHighlight();
      commandVisuals?.dispose();
      renderBatches?.dispose();
      renderBatches = null;
      labelRenderer.domElement.remove();
      if (active) {
        world.remove(active.root);
        disposeScene(active);
        active = null;
      }
      highlights = null;
      linkedHighlights = null;
      pickMeshes = null;
      renderer.dispose();
    },
  };
}
