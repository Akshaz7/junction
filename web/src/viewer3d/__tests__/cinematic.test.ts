import { describe, expect, it } from 'vitest';
import { DIM_OPACITY, ORBIT_MS, planCinematic, sampleCinematic } from '../cinematic';

describe('answer cinematic timeline', () => {
  it('orbits once in about 3 s with ease in/out and ends where it started', () => {
    const plan = planCinematic(5, true);
    expect(plan.orbitMs).toBe(ORBIT_MS);
    expect(sampleCinematic(plan, 0).orbitAngle).toBe(0);
    const early = sampleCinematic(plan, 150).orbitAngle!;
    const middle = sampleCinematic(plan, ORBIT_MS / 2).orbitAngle!;
    expect(early).toBeLessThan(Math.PI * 2 * (150 / ORBIT_MS)); // eased in
    expect(middle).toBeCloseTo(Math.PI, 5);
    expect(sampleCinematic(plan, ORBIT_MS).orbitAngle).toBeNull();
    expect(sampleCinematic(plan, ORBIT_MS).orbitDone).toBe(true);
  });
  it('has no orbit when the user is interacting', () => {
    const plan = planCinematic(3, false);
    expect(sampleCinematic(plan, 100).orbitAngle).toBeNull();
    expect(sampleCinematic(plan, 0).orbitDone).toBe(true);
  });
  it('lights items one by one in reading order, pulsing above the settled glow', () => {
    const plan = planCinematic(4, true);
    const at = (i: number) => plan.lightStartMs + i * plan.stepMs;
    const before = sampleCinematic(plan, at(1) - 1);
    expect(before.glow[0]).toBeGreaterThan(0);
    expect(before.glow[1]).toBe(0);
    expect(before.popped).toEqual([true, false, false, false]);
    const peak = Math.max(...Array.from({ length: 45 }, (_, k) => sampleCinematic(plan, at(2) + k * 10).glow[2]));
    expect(peak).toBeGreaterThan(1.5);
    expect(sampleCinematic(plan, plan.endMs).glow).toEqual([1, 1, 1, 1]);
  });
  it('dims the rest in, holds, and releases once everything is lit', () => {
    const plan = planCinematic(6, true);
    expect(sampleCinematic(plan, 0).dim).toBe(0);
    expect(sampleCinematic(plan, 400).dim).toBe(1);
    expect(sampleCinematic(plan, plan.lightEndMs - 1).dim).toBe(1);
    expect(sampleCinematic(plan, plan.endMs).dim).toBe(0);
    expect(DIM_OPACITY).toBeGreaterThan(0.4);
  });
  it('stays short for very large answers', () => {
    const plan = planCinematic(400, true);
    expect(plan.endMs).toBeLessThan(15_000);
  });
});
