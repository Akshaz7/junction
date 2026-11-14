/** Pure timeline for the answer "reveal": dim the rest, orbit once, light the answer items one by one. */
export const ORBIT_MS = 3000;
export const DIM_IN_MS = 300;
export const DIM_OUT_MS = 350;
export const DIM_OPACITY = 0.55;
const LIGHT_START_MS = 500;
const LIGHT_SPAN_MS = 2400;
const PULSE_MS = 450;
const PEAK = 2.2;

export interface CinematicPlan {
  count: number;
  orbit: boolean;
  orbitMs: number;
  lightStartMs: number;
  stepMs: number;
  pulseMs: number;
  /** Time at which the last item has finished pulsing. */
  lightEndMs: number;
  endMs: number;
}

export interface CinematicSample {
  /** Radians around the vertical axis, 0 → 2π, eased in and out; null when there is no orbit or it has finished. */
  orbitAngle: number | null;
  /** 0 = nothing dimmed, 1 = the rest of the model at DIM_OPACITY. */
  dim: number;
  /** Per answer item (reading order): emissive factor, 0 unlit, up to ~2.2 at the pulse peak, 1 settled. */
  glow: number[];
  /** Per answer item: has its numbered tag popped in? */
  popped: boolean[];
  orbitDone: boolean;
  done: boolean;
}

const smooth = (t: number) => { const x = Math.min(1, Math.max(0, t)); return x * x * (3 - 2 * x); };

export function planCinematic(count: number, orbit: boolean): CinematicPlan {
  const stepMs = count > 1 ? Math.min(400, Math.max(25, LIGHT_SPAN_MS / count)) : 0;
  const lightEndMs = LIGHT_START_MS + Math.max(0, count - 1) * stepMs + PULSE_MS;
  const orbitMs = orbit ? ORBIT_MS : 0;
  return { count, orbit, orbitMs, lightStartMs: LIGHT_START_MS, stepMs, pulseMs: PULSE_MS, lightEndMs,
    endMs: Math.max(orbitMs, lightEndMs + DIM_OUT_MS) };
}

export function glowAt(plan: CinematicPlan, index: number, t: number): number {
  const s = t - (plan.lightStartMs + index * plan.stepMs);
  if (s < 0) return 0;
  if (s >= plan.pulseMs) return 1;
  const p = s / plan.pulseMs;
  return p < 0.4 ? smooth(p / 0.4) * PEAK : PEAK - (PEAK - 1) * smooth((p - 0.4) / 0.6);
}

export function sampleCinematic(plan: CinematicPlan, t: number): CinematicSample {
  const dimIn = smooth(t / DIM_IN_MS);
  const dimOut = smooth((t - plan.lightEndMs) / DIM_OUT_MS);
  const orbiting = plan.orbit && t < plan.orbitMs;
  return {
    orbitAngle: orbiting ? Math.PI * 2 * smooth(t / plan.orbitMs) : null,
    dim: Math.max(0, Math.min(dimIn, 1 - dimOut)),
    glow: Array.from({ length: plan.count }, (_, i) => glowAt(plan, i, t)),
    popped: Array.from({ length: plan.count }, (_, i) => t >= plan.lightStartMs + i * plan.stepMs),
    orbitDone: !plan.orbit || t >= plan.orbitMs,
    done: t >= plan.endMs,
  };
}
