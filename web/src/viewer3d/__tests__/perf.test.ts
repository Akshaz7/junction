import { describe, expect, it } from 'vitest';
import { createFrameProbe } from '../perf';

describe('real frame-time probe', () => {
  it('measures frame intervals and time through the first rendered scene frame', () => {
    const probe = createFrameProbe();
    probe.beginLoad(100);
    probe.frame(150, false);
    probe.frame(200, true);
    for (let now = 216; now <= 1840; now += 16) probe.frame(now, true);
    probe.frame(1900, true);
    expect(probe.read(12, 345)).toEqual({
      frames: 104, p50_ms: 16, p95_ms: 16, draw_calls: 12, triangles: 345, load_ms: 100,
    });
    probe.reset();
    probe.frame(2000, true);
    probe.frame(2040, true);
    expect(probe.read(1, 2)).toMatchObject({ frames: 2, p50_ms: 40, p95_ms: 40, load_ms: 100 });
  });

  it('does not report invented samples before frames exist and keeps a slow p95 visible', () => {
    const probe = createFrameProbe();
    expect(probe.read(0, 0)).toMatchObject({ frames: 0, p50_ms: 0, p95_ms: 0 });
    for (const now of [0, 16, 32, 48, 64, 80, 96, 112, 128, 144, 244]) probe.frame(now, true);
    expect(probe.read(1, 2)).toMatchObject({ p50_ms: 16, p95_ms: 100 });
  });
});
