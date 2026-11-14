import type { Object3D } from 'three';
import type { LoadedScene } from './scene';

export type RisePhase = 'flat' | 'rising' | 'done';
export interface RiseState { phase: RisePhase; progress: number }
export const FLAT_DURATION_MS = 600;
export const RISE_DURATION_MS = 1200;

/** Progress follows elapsed time, including when rendering skips frames. */
export function riseState(elapsedMs: number, reducedMotion = false): RiseState {
  if (reducedMotion) return { phase: 'done', progress: 1 };
  if (elapsedMs <= FLAT_DURATION_MS) return { phase: 'flat', progress: 0 };
  const t = Math.min(1, (elapsedMs - FLAT_DURATION_MS) / RISE_DURATION_MS);
  return { phase: t === 1 ? 'done' : 'rising', progress: t * t * (3 - 2 * t) };
}

/** Keep phase changes observable even when requestAnimationFrame is delayed. */
export function scheduleRiseTransitions(sample: () => void): () => void {
  const timers = [
    setTimeout(sample, FLAT_DURATION_MS + 1),
    setTimeout(sample, FLAT_DURATION_MS + RISE_DURATION_MS),
  ];
  return () => { timers.forEach(clearTimeout); };
}

export function createRiseAnimation(scene: LoadedScene, startedAt: number, reducedMotion = false) {
  const originals = new Map<Object3D, number>();
  for (const [id, object] of scene.items) {
    if (['wall', 'door', 'window'].includes(scene.manifest.items[id].kind)) {
      originals.set(object, object.scale.y);
    }
  }
  return {
    sample(now: number): RiseState {
      const state = riseState(now - startedAt, reducedMotion);
      for (const [object, scaleY] of originals) object.scale.y = scaleY * state.progress;
      scene.root.updateWorldMatrix(true, true);
      return state;
    },
    restore(): void {
      for (const [object, scaleY] of originals) object.scale.y = scaleY;
      scene.root.updateWorldMatrix(true, true);
    },
  };
}
