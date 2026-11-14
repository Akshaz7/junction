/** Coalesce pointer/range events; only the newest value is applied in a frame. */
export function frameThrottle<T>(apply: (value: T) => void) {
  let frame: number | null = null;
  let latest: T;
  return {
    schedule(value: T) {
      latest = value;
      if (frame !== null) return;
      frame = requestAnimationFrame(() => { frame = null; apply(latest); });
    },
    cancel() {
      if (frame !== null) cancelAnimationFrame(frame);
      frame = null;
    },
  };
}
