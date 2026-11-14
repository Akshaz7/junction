export interface ViewerPerf {
  frames: number;
  p50_ms: number;
  p95_ms: number;
  draw_calls: number;
  triangles: number;
  load_ms: number;
}

/** RAF intervals include rendering, GPU stalls and browser scheduling, in milliseconds. */
export function createFrameProbe() {
  const intervals: number[] = [];
  let previous: number | undefined;
  let frames = 0;
  let loadMs = 0;
  let pendingLoad: number | undefined;
  return {
    beginLoad(now: number) { pendingLoad = now; loadMs = 0; },
    reset() { intervals.length = 0; previous = undefined; frames = 0; },
    frame(now: number, hasScene: boolean) {
      if (!hasScene) return;
      if (pendingLoad !== undefined) { loadMs = now - pendingLoad; pendingLoad = undefined; }
      if (previous !== undefined && now > previous) intervals.push(now - previous);
      // Bound memory during a long-running workspace session.
      if (intervals.length > 3600) intervals.shift();
      previous = now;
      frames++;
    },
    read(drawCalls: number, triangles: number): ViewerPerf {
      const sorted = [...intervals].sort((a, b) => a - b);
      const percentile = (p: number) => sorted[Math.max(0, Math.ceil(sorted.length * p) - 1)] ?? 0;
      return { frames, p50_ms: percentile(0.5), p95_ms: percentile(0.95),
        draw_calls: drawCalls, triangles, load_ms: loadMs };
    },
  };
}
