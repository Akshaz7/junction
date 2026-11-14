import { Vector3, type Object3D } from 'three';
import type { LoadedScene, SceneManifest } from './scene';
import { storeyName } from './scene';

/** flat = the plan before step 1 grows, rising = building up (or scrubbed part-way), done = finished model. */
export type RisePhase = 'flat' | 'rising' | 'done';
export interface RiseState { phase: RisePhase; progress: number }

export const FLAT_DURATION_MS = 600;
export const MIN_STEP_MS = 200;
export const MAX_STEP_MS = 600;
const TARGET_TOTAL_MS = 7000;

export interface BuildStep { label: string; ids: string[] }

export interface BuildState {
  /** 1-based step shown on the slider (the step being built, or the last completed one). */
  index: number;
  total: number;
  label: string;
  playing: boolean;
  phase: RisePhase;
  /** Whole build-up, 0..1. */
  progress: number;
}

const PLAN_MAP_ID = /^[a-z_]+-\d+$/;

/** Plan-map and DXF scenes use `<kind>-<n>` ids; IFC scenes use GlobalIds. */
export function isIfcManifest(manifest: Pick<SceneManifest, 'items'>): boolean {
  return Object.keys(manifest.items).some((id) => !PLAN_MAP_ID.test(id));
}

type Bucket = 'foundations' | 'slab' | 'structure' | 'walls' | 'stairs' | 'openings' | 'roof' | 'ground';

function ifcBucket(kind: string): Bucket {
  switch (kind) {
    case 'footing': case 'pile': return 'foundations';
    case 'slab': case 'covering': case 'room': return 'slab';
    case 'column': case 'beam': case 'member': case 'plate': return 'structure';
    case 'wall': case 'curtain_wall': return 'walls';
    case 'stairs': case 'ramp': case 'railing': return 'stairs';
    case 'roof': return 'roof';
    case 'site': return 'ground';
    default: return 'openings';
  }
}

const BUCKET_LABEL: Record<Bucket, string> = {
  foundations: 'Foundations', slab: 'slab', structure: 'columns and beams', walls: 'walls',
  stairs: 'stairs', openings: 'doors and windows', roof: 'Roof', ground: '',
};
const STOREY_BUCKETS: Bucket[] = ['slab', 'structure', 'walls', 'stairs', 'openings'];

/**
 * IFC: foundations, then per storey (lowest first) slab, columns/beams, walls, stairs, doors/windows, then roof.
 * Raster/DXF: floor, walls, doors/windows. Empty IFC steps are dropped; items with no step stay visible.
 */
export function buildSteps(manifest: Pick<SceneManifest, 'items' | 'storeys'>): BuildStep[] {
  const entries = Object.entries(manifest.items);
  if (!isIfcManifest(manifest)) {
    const floor: string[] = [], walls: string[] = [], openings: string[] = [];
    for (const [id, item] of entries) {
      if (item.kind === 'room') floor.push(id);
      else if (item.kind === 'wall' || item.kind === 'column') walls.push(id);
      else openings.push(id);
    }
    const steps: BuildStep[] = [{ label: 'Floor', ids: floor }];
    if (walls.length) steps.push({ label: 'Walls', ids: walls });
    if (openings.length) steps.push({ label: 'Doors and windows', ids: openings });
    return steps;
  }
  const ordered = [...manifest.storeys]
    .map((storey, index) => ({ name: storeyName(storey), elevation: typeof storey === 'string' ? index : storey.elevation_m ?? index }))
    .filter((entry): entry is { name: string; elevation: number } => entry.name !== null)
    .sort((a, b) => a.elevation - b.elevation);
  const lowest = ordered[0]?.name ?? null;
  const cells = new Map<string, string[]>();
  const push = (key: string, id: string) => { (cells.get(key) ?? cells.set(key, []).get(key)!).push(id); };
  for (const [id, item] of entries) {
    const bucket = ifcBucket(item.kind);
    if (bucket === 'foundations' || bucket === 'roof') { push(bucket, id); continue; }
    if (bucket === 'ground') continue;
    const name = storeyName(item.storey) ?? lowest;
    push(`${name}\u0000${bucket}`, id);
  }
  const names = [...ordered.map((entry) => entry.name)];
  for (const key of cells.keys()) {
    const name = key.split('\u0000')[0];
    if (key.includes('\u0000') && name !== 'null' && !names.includes(name)) names.push(name);
  }
  const steps: BuildStep[] = [];
  const add = (label: string, key: string) => { const ids = cells.get(key); if (ids?.length) steps.push({ label, ids }); };
  add(BUCKET_LABEL.foundations, 'foundations');
  for (const name of names) for (const bucket of STOREY_BUCKETS) add(`${name} ${BUCKET_LABEL[bucket]}`, `${name}\u0000${bucket}`);
  add(BUCKET_LABEL.roof, 'roof');
  if (!steps.length) steps.push({ label: 'Model', ids: entries.map(([id]) => id) });
  return steps;
}

export function stepDurationMs(total: number): number {
  return Math.min(MAX_STEP_MS, Math.max(MIN_STEP_MS, TARGET_TOTAL_MS / Math.max(1, total)));
}

const ease = (t: number) => t * t * (3 - 2 * t);

interface Managed { object: Object3D; scaleY: number; posY: number; pivot: number; step: number; id: string }

export interface BuildAnimationOptions {
  reducedMotion?: boolean;
  /** Items that must stay fully visible whatever the step (the current answer's highlights). */
  pinned?: () => ReadonlySet<string> | readonly string[];
  /** Start playing (after the flat intro) instead of waiting on the slider. Ignored under reduced motion. */
  autoplay?: boolean;
  /** Only these items take part in the build (the cut storey and below; the roof only when shown). */
  include?: (id: string) => boolean;
}

/**
 * Staged build-up: step j grows (scale.y from its own base) while the position advances.
 * Position `p` is 0..N: steps 1..floor(p) are complete, step floor(p)+1 is growing.
 */
export function createBuildAnimation(scene: LoadedScene, startedAt: number, options: BuildAnimationOptions = {}) {
  const include = options.include;
  const steps = buildSteps(scene.manifest)
    .map((step) => include ? { ...step, ids: step.ids.filter(include) } : step)
    .filter((step) => step.ids.length);
  if (!steps.length) steps.push({ label: 'Model', ids: Object.keys(scene.manifest.items) });
  const total = steps.length;
  const stepMs = stepDurationMs(total);
  const managed: Managed[] = [];
  const parentY = new Vector3();
  scene.root.updateWorldMatrix(true, true);
  steps.forEach((step, stepIndex) => {
    for (const id of step.ids) {
      const object = scene.items.get(id);
      if (!object) continue;
      const bounds = scene.manifest.items[id].bbox_m;
      // Grow from the item's own base: world min-y from the manifest, parent offset from the live graph.
      object.parent?.getWorldPosition(parentY);
      managed.push({ object, scaleY: object.scale.y, posY: object.position.y, id,
        pivot: bounds ? bounds[0][1] - (object.parent ? parentY.y : 0) : 0, step: stepIndex });
    }
  });
  const reduced = options.reducedMotion === true;
  let position = reduced ? total : 0;
  let playing = !reduced && options.autoplay !== false;
  let anchor = { t: startedAt + FLAT_DURATION_MS, p: 0 };

  function currentPosition(now: number): number {
    if (!playing) return position;
    return Math.min(total, anchor.p + Math.max(0, now - anchor.t) / stepMs);
  }
  function indexOf(p: number): number { return Math.min(total, Math.max(1, Math.ceil(p))); }

  function place(entry: Managed, factor: number): void {
    const { object } = entry;
    if (factor >= 1) {
      object.scale.y = entry.scaleY; object.position.y = entry.posY;
    } else {
      const s = Math.max(0, factor);
      object.scale.y = entry.scaleY * s;
      object.position.y = entry.posY + (1 - s) * (entry.pivot - entry.posY);
    }
  }

  function snapshot(p: number, now: number): BuildState {
    const index = indexOf(p);
    const finished = p >= total;
    const intro = playing && now < anchor.t && p === 0;
    return {
      index, total, label: steps[index - 1]?.label ?? '', playing: playing && !finished,
      phase: finished ? 'done' : intro || (p === 0 && playing) ? 'flat' : 'rising',
      progress: total ? p / total : 1,
    };
  }

  const api = {
    steps,
    total,
    stepMs,
    /** Applies the state at `now` to the scene and returns it. */
    sample(now: number): BuildState {
      const p = currentPosition(now);
      if (playing && p >= total) { position = total; playing = false; }
      const pinned = new Set(options.pinned?.() ?? []);
      for (const entry of managed) {
        place(entry, pinned.has(entry.id) ? 1 : ease(Math.min(1, Math.max(0, p - entry.step))));
      }
      scene.root.updateWorldMatrix(true, true);
      return snapshot(playing ? p : position, now);
    },
    state(now: number): BuildState { return snapshot(currentPosition(now), now); },
    play(now: number): void {
      if (position >= total) position = 0;
      playing = true;
      anchor = { t: now, p: position };
    },
    pause(now: number): void {
      if (!playing) return;
      position = Math.min(total, Math.ceil(currentPosition(now) - 1e-9));
      playing = false;
    },
    /** Shows steps 1..index complete. Scrubbing pauses playback. */
    setStep(index: number): void {
      position = Math.min(total, Math.max(1, Math.round(index)));
      playing = false;
    },
    /** Continuous scrubbing uses the existing nodes and their saved base transforms. */
    setPosition(value: number): void {
      if (!Number.isFinite(value)) return;
      position = Math.min(total, Math.max(0, value));
      playing = false;
    },
    /** Milliseconds until the flat intro ends and until the build finishes, for timer scheduling. */
    timeline(now: number): { introMs: number; finishMs: number } | null {
      if (!playing) return null;
      return { introMs: Math.max(0, anchor.t - now), finishMs: Math.max(0, anchor.t - now) + (total - anchor.p) * stepMs };
    },
    /** Full geometry again, e.g. before measuring bounds. */
    restore(): void {
      for (const entry of managed) place(entry, 1);
      scene.root.updateWorldMatrix(true, true);
    },
  };
  return api;
}

export type BuildAnimation = ReturnType<typeof createBuildAnimation>;

/** Keep phase changes observable even when requestAnimationFrame is delayed. */
export function scheduleBuildTransitions(sample: () => void, timeline: { introMs: number; finishMs: number } | null): () => void {
  if (!timeline) return () => {};
  const timers = [setTimeout(sample, timeline.introMs + 1), setTimeout(sample, timeline.finishMs + 1)];
  return () => { timers.forEach(clearTimeout); };
}
