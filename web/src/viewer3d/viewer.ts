import {
  AmbientLight, Box3, Color, DirectionalLight, PerspectiveCamera,
  Plane, Raycaster, Scene, Sphere, Vector2, Vector3, WebGLRenderer,
} from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { type CSS2DObject, CSS2DRenderer } from 'three/examples/jsm/renderers/CSS2DRenderer.js';
import {
  createHighlightController, itemBounds, readHighlightColor, type HighlightOptions, type HighlightState,
} from './highlight';
import {
  disposeScene, itemIdForObject, loadScene, type LoadedScene,
} from './scene';
import { createCutawayController, type CutawayState } from './cutaway';
import { createLinkedHighlightController } from './linkedHighlight';
import { createBuildAnimation, scheduleBuildTransitions, FLAT_DURATION_MS, type BuildAnimation, type BuildState, type RisePhase, type RiseState } from './rise';
import { applyCommand, applyState, emptyCommandState, readCommandState, resolveCommandLabels, type SceneCommand, type SceneSnapshot, type CommandTestState } from './commands';
import { createCommandVisuals } from './commandVisuals';
import { createFrameProbe, type ViewerPerf } from './perf';
import { createRenderBatches, PICK_LAYER } from './renderBatches';
import { withAbort, type LoadProgress } from './loadGLTF';
import { createWalkController, type WalkState } from './walk';
import { createEditLayer, type ItemEdit, type EditState, type WallMaterial } from './edits';
import { createItemAnnotation, layoutAnnotations } from './annotations';
import { createFindingsLayer, type Finding, type FindingPinState } from './findings';
import { kindColor } from '../lib/kind-colors';
import { planCinematic, sampleCinematic, type CinematicPlan } from './cinematic';

export const SCENE_LOAD_BUDGET_MS = 60_000;

export interface CinematicState { active: boolean; orbit: boolean; total: number; lit: number; popped: number; dim: number; angle: number | null }

export interface Viewer {
  readonly renderer: WebGLRenderer;
  readonly camera: PerspectiveCamera;
  readonly controls: OrbitControls;
  readonly scene: LoadedScene | null;
  itemScreenPosition(item_id: string): { x: number; y: number; visible: boolean } | null;
  perf(): ViewerPerf;
  resetPerf(): void;
  setFindings(findings: readonly Finding[], onSelect?: (findings: Finding[]) => void): void;
  findings(): FindingPinState[];
  /** Select a finding sprite before testing building meshes on a click/tap. */
  pickFinding(x: number, y: number): boolean;
  walk(): WalkState;
  setWalk(active: boolean): boolean;
  setWalkJoystick(x: number, y: number): void;
  onWalkChange(callback: (state: WalkState) => void): () => void;
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
  getEditState(): EditState;
  removeItem(item_id: string): ItemEdit | null;
  changeMaterial(item_id: string, material: WallMaterial): ItemEdit | null;
  undoEdit(): ItemEdit | null;
  resetEdits(): ItemEdit | null;
  beginMove(item_id: string, x: number, y: number): boolean;
  updateMove(x: number, y: number): void;
  endMove(cancel?: boolean): ItemEdit | null;
  /** Show the flat plan/top-down IFC view, then raise the architectural items. */
  visualise(onStateChange?: (state: RiseState) => void): void;
  /** Staged build-up (FIX-5): null until visualise() has run, and after walk/edit end it. */
  getBuildState(): BuildState | null;
  /** The answer reveal (orbit, dim, one-by-one pulse), for tests and the UI. */
  getCinematicState(): CinematicState;
  onBuildChange(callback: (state: BuildState | null) => void): () => void;
  /** Show steps 1..index complete (1-based). Pauses playback; the camera is not touched. */
  setBuildStep(index: number): void;
  playBuild(): void;
  pauseBuild(): void;
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
  let findingPins: ReturnType<typeof createFindingsLayer> | null = null;
  // Populated on the first pointer interaction, never during model loading.
  let pickMeshes: Scene['children'] | null = null;
  let renderBatches: ReturnType<typeof createRenderBatches> | null = null;
  let batchesDirty = false;
  let cutaway: ReturnType<typeof createCutawayController> | null = null;
  const cutawayListeners = new Set<(state: CutawayState) => void>();
  function notifyCutaway(): void {
    batchesDirty = true;
    walk.syncStorey();
    if (cutaway) for (const listener of cutawayListeners) listener(cutaway.getState());
  }
  let disposed = false;
  let loadVersion = 0;
  let pendingLoad: AbortController | null = null;
  let highlights: ReturnType<typeof createHighlightController> | null = null;
  let linkedHighlights: ReturnType<typeof createLinkedHighlightController> | null = null;
  let commandVisuals: ReturnType<typeof createCommandVisuals> | null = null;
  let commandState = emptyCommandState();
  let edits: ReturnType<typeof createEditLayer> | null = null;
  let moving: { id: string; from: Vector3; start: Vector3; plane: Plane; dx: number; dz: number; controlsEnabled: boolean } | null = null;
  let applyingCommand = false;
  const commandListeners = new Set<(command: SceneCommand) => void>();
  let linked = { hovered: null as string | null, selected: null as string | null, labels: {} as Record<string, string> };
  let linkedLabel: CSS2DObject | null = null;
  const highlightListeners = new Set<(state: HighlightState) => void>();
  const labels: CSS2DObject[] = [];
  let flight: { start: number; from: Vector3; to: Vector3; targetFrom: Vector3; targetTo: Vector3 } | null = null;
  let cameraTarget: string | null = null;
  const walkListeners = new Set<(state: WalkState) => void>();
  const walk = createWalkController(canvas, camera, controls, {
    getScene: () => active,
    getStorey: () => cutaway?.getState().activeStorey ?? null,
    getTarget: () => cameraTarget,
    setStorey,
    onChange(state) { for (const callback of walkListeners) callback(state); },
  });
  let build: {
    animation: BuildAnimation; from: Vector3; to: Vector3; introStart: number; intro: boolean; dirty: boolean;
    key: string; phase: RisePhase; onStateChange?: (state: RiseState) => void; cancelTransitions: () => void;
  } | null = null;
  const buildListeners = new Set<(state: BuildState | null) => void>();
  function emitBuild(state: BuildState | null): void { for (const listener of buildListeners) listener(state); }
  /** Back to the finished model: restores every transform and hides the slider. */
  function endBuild(): void {
    if (!build) return;
    build.cancelTransitions();
    build.animation.restore();
    const previous = build;
    build = null;
    batchesDirty = true;
    previous.onStateChange?.({ phase: 'done', progress: 1 });
    emitBuild(null);
  }
  const raycaster = new Raycaster();
  raycaster.layers.enable(PICK_LAYER);
  const pointer = new Vector2();

  function mutateEdit(action: () => ItemEdit | null): ItemEdit | null {
    if (!active || disposed) return null;
    // Unwind interaction layers before replacing any base material. Recreate the
    // lazy selection index so future hover/highlight uses the edited surface.
    const previous = highlights?.getHighlightState();
    clearHighlight();
    linkedHighlights = null;
    const result = action();
    if (previous?.highlighted.length) highlight(previous.highlighted, { labels: previous.labels, dimOthers: commandState.isolated === null });
    else { applyLinkedVisuals(); notifyHighlight(); }
    batchesDirty = true;
    return result;
  }

  function floorPoint(x: number, y: number, plane: Plane): Vector3 | null {
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    pointer.set((x - rect.left) / rect.width * 2 - 1, -(y - rect.top) / rect.height * 2 + 1);
    camera.updateWorldMatrix(true, false);
    raycaster.setFromCamera(pointer, camera);
    return raycaster.ray.intersectPlane(plane, new Vector3());
  }

  function endMove(cancel = false): ItemEdit | null {
    if (!moving) return null;
    const drag = moving; moving = null;
    controls.enabled = drag.controlsEnabled;
    if (cancel) {
      active?.items.get(drag.id)?.position.copy(drag.from);
      batchesDirty = true;
      return null;
    }
    return mutateEdit(() => edits?.move(drag.id, drag.from, drag.dx, drag.dz, true) ?? null);
  }

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
    endCinematic();
    batchesDirty = true;
    if (build) build.dirty = true;
    commandVisuals?.clearMaterials();
    flight = null;
    cameraTarget = null;
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
    // in the full geometry frame before returning to the current build step.
    build?.animation.restore();
    const bounds = itemBounds(active, [id]);
    if (bounds.isEmpty()) { build?.animation.sample(performance.now()); return; }
    linkedLabel = createItemAnnotation(active, id, getLinkedHighlightState().labels[id]);
    build?.animation.sample(performance.now());
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
    cameraTarget = options.cameraTargetItemId ?? null;
    cutaway?.followHighlight(ids, options.cameraTargetItemId);
    commandVisuals?.captureVisibility();
    notifyCutaway();
    // Compute labels using full geometry: a flat node has a singular world matrix.
    build?.animation.restore();
    const scene = active;
    highlights.highlight(ids, options, (id) => new Color(kindColor(scene.manifest.items[id]?.kind)));
    const state = highlights.getHighlightState();
    for (const id of state.highlighted) {
      const label = createItemAnnotation(active, id, state.labels[id]);
      if (label) labels.push(label);
    }
    const target = options.cameraTargetItemId && active.items.has(options.cameraTargetItemId)
      ? options.cameraTargetItemId : state.highlighted[0];
    cameraTarget = target ?? null;
    applyLinkedVisuals();
    // Highlights stay fully visible while the model builds up (they are pinned in the animation).
    if (build) build.animation.sample(performance.now());
    const canFly = !(build && build.phase !== 'done') && !walk.state().active;
    if (canFly) {
      // An explicit camera target wins; otherwise frame every highlighted item so all numbered tags stay in view.
      const fly = itemBounds(active, options.cameraTargetItemId && active.items.has(options.cameraTargetItemId) ? [options.cameraTargetItemId] : state.highlighted);
      const reveal = options.cinematic === true && !prefersReducedMotion() && state.highlighted.length > 0
        && !fly.isEmpty() && performance.now() - sceneShownAt > REVEAL_AFTER_LOAD_MS;
      if (reveal) startCinematic(state.highlighted, fly); else flyTo(fly);
    }
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
      const cinematic = cinematicNext; cinematicNext = false;
      highlight([...commandState.highlighted.keys()], { labels, dimOthers: commandState.isolated === null, cinematic });
    } finally { applyingCommand = false; }
  }

  // --- Answer reveal: dim the rest, orbit once (unless the user is interacting), light items one by one. ---
  const UP = new Vector3(0, 1, 0);
  const USER_IDLE_MS = 1500;
  const REVEAL_AFTER_LOAD_MS = 2000;
  let sceneShownAt = 0;
  let userDragging = false;
  let lastInteraction = -Infinity;
  let cinematicNext = false;
  let cine: { plan: CinematicPlan; start: number; ids: string[]; basePos: Vector3; target: Vector3; focus: Set<string>;
    fly: Box3 | null; cancelled: boolean; settled: boolean; last: ReturnType<typeof sampleCinematic> } | null = null;
  const userBusy = (now: number) => userDragging || now - lastInteraction < USER_IDLE_MS || moving !== null || walk.state().active;
  const prefersReducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function setLabelPop(popped: (id: string) => boolean | null): void {
    for (const label of labels) {
      const state = popped(label.element.dataset.itemId ?? '');
      if (state === null) delete label.element.dataset.pop;
      else label.element.dataset.pop = state ? 'in' : 'hidden';
    }
  }

  function startCinematic(ids: string[], fly: Box3): void {
    const now = performance.now();
    if (!ids.length || !commandVisuals || !highlights) { flyTo(fly); return; }
    const orbit = !userBusy(now);
    const plan = planCinematic(ids.length, orbit);
    cine = { plan, start: now, ids, basePos: camera.position.clone(), target: controls.target.clone(), focus: new Set(ids),
      fly, cancelled: false, settled: !orbit, last: sampleCinematic(plan, 0) };
    if (!orbit) flyTo(fly);
    stepCinematic(now);
  }

  function endCinematic(): void {
    const current = cine;
    if (!current) return;
    cine = null;
    for (const id of current.ids) highlights?.setGlow(id, 1);
    setLabelPop(() => null);
    commandVisuals?.setFocus(null, 0);
    batchesDirty = true;
  }

  function stepCinematic(now: number): void {
    const c = cine;
    if (!c || !highlights) return;
    const s = sampleCinematic(c.plan, now - c.start);
    c.last = s;
    if (!c.cancelled && s.orbitAngle !== null) {
      camera.position.copy(c.target).add(c.basePos.clone().sub(c.target).applyAxisAngle(UP, s.orbitAngle));
      camera.lookAt(c.target);
    } else if (!c.settled && s.orbitDone) {
      c.settled = true;
      if (!c.cancelled) {
        camera.position.copy(c.basePos);
        camera.lookAt(controls.target);
        if (c.fly) flyTo(c.fly);
      }
    }
    c.ids.forEach((id, index) => highlights!.setGlow(id, s.glow[index]));
    const popped = new Map(c.ids.map((id, index) => [id, s.popped[index]]));
    setLabelPop((id) => popped.get(id) ?? null);
    commandVisuals?.setFocus(c.focus, s.dim);
    batchesDirty = true;
    if (s.done) endCinematic();
  }

  function visualise(onStateChange?: (state: RiseState) => void): void {
    if (disposed || !active) return;
    walk.exit();
    batchesDirty = true;
    endBuild();
    flight = null;
    fit(active);
    const to = camera.position.clone();
    const distance = to.distanceTo(controls.target);
    // A tiny Z offset avoids the camera-up singularity at an exact overhead view.
    const from = controls.target.clone().add(new Vector3(0, distance, distance * 0.001));
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const now = performance.now();
    const animation = createBuildAnimation(active, now, {
      reducedMotion, pinned: () => highlights?.getHighlightState().highlighted ?? [],
    });
    const state = animation.sample(now);
    build = { animation, from, to, introStart: now, intro: !reducedMotion, dirty: false, phase: state.phase,
      key: `${state.index}|${state.playing}|${state.phase}`, onStateChange,
      cancelTransitions: scheduleBuildTransitions(sampleRise, animation.timeline(now)) };
    if (!reducedMotion) {
      camera.position.copy(from);
      camera.lookAt(controls.target);
    }
    onStateChange?.({ phase: state.phase, progress: state.progress });
    emitBuild(state);
  }

  function sampleRise(): void {
    const current = build;
    if (!current || disposed) return;
    const now = performance.now();
    const peek = current.animation.state(now);
    if (!peek.playing && !current.dirty && peek.phase === current.phase) return;
    current.dirty = false;
    const state = current.animation.sample(now);
    // The overhead-to-3/4 move only happens on the first, hands-off play; any orbit/zoom ends it.
    if (current.intro) {
      const t = Math.min(1, Math.max(0, (now - current.introStart - FLAT_DURATION_MS) / 1000));
      camera.position.lerpVectors(current.from, current.to, t * t * (3 - 2 * t));
      camera.lookAt(controls.target);
      if (t >= 1) current.intro = false;
    }
    if (state.playing) batchesDirty = true;
    const key = `${state.index}|${state.playing}|${state.phase}`;
    if (key !== current.key) { current.key = key; batchesDirty = true; emitBuild(state); }
    if (state.phase !== current.phase) {
      const previous = current.phase;
      current.phase = state.phase;
      current.onStateChange?.({ phase: state.phase, progress: state.progress });
      if (state.phase === 'done') {
        current.intro = false;
        if (previous !== 'done' && cameraTarget && active) flyTo(itemBounds(active, [cameraTarget]));
      }
    }
  }

  function touchBuild(): void {
    if (!build) return;
    build.dirty = true;
    build.cancelTransitions();
    build.cancelTransitions = scheduleBuildTransitions(sampleRise, build.animation.timeline(performance.now()));
    sampleRise();
  }

  // Direct orbit/zoom input takes over the camera (and the intro move), never the build-up itself.
  controls.addEventListener('end', () => { userDragging = false; lastInteraction = performance.now(); });
  controls.addEventListener('start', () => {
    userDragging = true; lastInteraction = performance.now();
    if (cine) cine.cancelled = true;
    flight = null;
    if (build) build.intro = false;
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
    walk.exit();
    endBuild();
    endMove(true);
    clearHighlight();
    findingPins?.dispose(); findingPins = null;
    commandVisuals?.dispose();
    edits?.dispose();
    renderBatches?.dispose();
    renderBatches = null;
    if (active) {
      world.remove(active.root);
      disposeScene(active);
    }
    active = scene;
    pickMeshes = null;
    commandState = emptyCommandState();
    sceneShownAt = performance.now();
    edits = createEditLayer(scene, { apply: (command) => api.applyCommand(command), hidden: () => [...commandState.hidden] });
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
  let previousFrame = performance.now();
  function render(): void {
    if (disposed) return;
    const now = performance.now();
    const dt = (now - previousFrame) / 1000;
    previousFrame = now;
    if (walk.state().active) walk.update(dt);
    else controls.update();
    const wasRising = build !== null && build.animation.state(performance.now()).playing;
    sampleRise();
    stepCinematic(now);
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
    findingPins?.update(camera, canvas.clientHeight);
    renderer.render(world, camera);
    if (labels.length || linkedLabel || findingPins) {
      labelRenderer.render(world, camera);
      if (active) layoutAnnotations(linkedLabel ? [...labels, linkedLabel] : labels, active, camera,
        canvas.clientWidth, canvas.clientHeight);
    }
    probe.frame(performance.now(), active !== null);
    frame = requestAnimationFrame(render);
  }
  render();

  function setStorey(name: string | null): void {
    cutaway?.setStorey(name);
    commandVisuals?.captureVisibility();
    commandVisuals?.sample(performance.now());
    notifyCutaway();
  }

  const api: Viewer = {
    renderer, camera, controls,
    itemScreenPosition(id) {
      if (!active || disposed) return null;
      const object = active.items.get(id);
      if (!object) return null;
      const bounds = itemBounds(active, [id]);
      if (bounds.isEmpty()) return null;
      const point = bounds.getCenter(new Vector3());
      const projected = point.project(camera);
      return { x: (projected.x + 1) * canvas.clientWidth / 2, y: (1 - projected.y) * canvas.clientHeight / 2,
        visible: itemIdForObject(active, object) !== null && projected.z >= -1 && projected.z <= 1
          && Math.abs(projected.x) <= 1 && Math.abs(projected.y) <= 1 };
    },
    perf: () => probe.read(renderer.info.render.calls, renderer.info.render.triangles),
    resetPerf: () => probe.reset(),
    setFindings(findings, onSelect = () => {}) {
      findingPins?.dispose(); findingPins = null;
      if (!active || disposed || !findings.length) return;
      findingPins = createFindingsLayer(active, onSelect);
      findingPins.set(findings);
      world.add(findingPins.root);
      findingPins.update(camera, canvas.clientHeight);
    },
    findings() {
      findingPins?.update(camera, canvas.clientHeight);
      return findingPins?.state(camera, canvas.getBoundingClientRect()) ?? [];
    },
    walk: () => walk.state(),
    setWalk(value) {
      if (disposed) return false;
      if (!value) { walk.exit(); return false; }
      if (walk.state().active) return true;
      flight = null;
      endBuild();
      return walk.enter();
    },
    setWalkJoystick: (x, y) => walk.joystick(x, y),
    onWalkChange(callback) { walkListeners.add(callback); return () => { walkListeners.delete(callback); }; },
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
    setStorey,
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
        ? { ...command, labels: resolveCommandLabels(command.item_ids, command.labels, active.manifest.items) } : command;
      commandState = applyCommand(commandState, resolved);
      cinematicNext = command.op === 'highlight' || command.op === 'isolate';
      renderCommandState();
      cinematicNext = false;
      for (const callback of commandListeners) callback(resolved);
    },
    applyState(snapshot) {
      if (!active || disposed) return;
      commandState = applyState({ ...snapshot,
        labels: resolveCommandLabels(snapshot.highlighted, snapshot.labels, active.manifest.items) });
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
    getEditState: () => edits?.state() ?? { undoCount: 0, moved: {}, materials: {} },
    removeItem: (id) => mutateEdit(() => edits?.remove(id) ?? null),
    changeMaterial: (id, choice) => mutateEdit(() => edits?.changeMaterial(id, choice) ?? null),
    undoEdit() { endMove(true); return mutateEdit(() => edits?.undo() ?? null); },
    resetEdits() { endMove(true); return mutateEdit(() => edits?.reset() ?? null); },
    beginMove(id, x, y) {
      if (disposed || !active || walk.state().active || !active.items.has(id) || commandState.hidden.has(id)) return false;
      endMove(true);
      flight = null;
      endBuild();
      const object = active.items.get(id)!;
      const bounds = itemBounds(active, [id]);
      if (bounds.isEmpty()) return false;
      const plane = new Plane(new Vector3(0, 1, 0), -bounds.min.y);
      const start = floorPoint(x, y, plane);
      if (!start) return false;
      moving = { id, from: object.position.clone(), start, plane, dx: 0, dz: 0, controlsEnabled: controls.enabled };
      controls.enabled = false;
      return true;
    },
    updateMove(x, y) {
      if (!moving || !edits) return;
      const point = floorPoint(x, y, moving.plane);
      if (!point) return;
      moving.dx = point.x - moving.start.x;
      moving.dz = point.z - moving.start.z;
      edits.move(moving.id, moving.from, moving.dx, moving.dz, false);
      batchesDirty = true;
    },
    endMove,
    getHighlightState() {
      return highlights?.getHighlightState() ?? { highlighted: [], dimmed: 0, labels: {} };
    },
    onHighlightChange(callback) {
      highlightListeners.add(callback);
      return () => { highlightListeners.delete(callback); };
    },
    visualise,
    getBuildState: () => build?.animation.state(performance.now()) ?? null,
    getCinematicState: () => {
      const s = cine?.last;
      return { active: cine !== null, orbit: cine?.plan.orbit ?? false, total: cine?.ids.length ?? 0,
        lit: s ? s.glow.filter((g) => g > 0).length : 0, popped: s ? s.popped.filter(Boolean).length : 0,
        dim: s?.dim ?? 0, angle: s?.orbitAngle ?? null };
    },
    onBuildChange(callback) { buildListeners.add(callback); return () => { buildListeners.delete(callback); }; },
    setBuildStep(index) { if (build) { build.animation.setStep(index); touchBuild(); } },
    playBuild() { if (build) { build.animation.play(performance.now()); touchBuild(); } },
    pauseBuild() { if (build) { build.animation.pause(performance.now()); touchBuild(); } },
    pickFinding(x, y) {
      if (disposed || !findingPins) return false;
      const rect = canvas.getBoundingClientRect();
      if (!rect.width || !rect.height || x < rect.left || x > rect.right || y < rect.top || y > rect.bottom) return false;
      findingPins.update(camera, canvas.clientHeight);
      pointer.set((x - rect.left) / rect.width * 2 - 1, -(y - rect.top) / rect.height * 2 + 1);
      raycaster.setFromCamera(pointer, camera);
      return findingPins.select(raycaster);
    },
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
      walkListeners.clear();
      walk.dispose();
      loadVersion++;
      pendingLoad?.abort(new Error('Viewer disposed'));
      pendingLoad = null;
      cancelAnimationFrame(frame);
      observer.disconnect();
      window.removeEventListener('resize', resize);
      controls.dispose();
      endBuild();
      buildListeners.clear();
      endMove(true);
      clearHighlight();
      findingPins?.dispose(); findingPins = null;
      commandVisuals?.dispose();
      edits?.dispose(); edits = null;
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
  return api;
}
