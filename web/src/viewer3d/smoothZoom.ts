import type { PerspectiveCamera, Vector3 } from 'three';

/** OrbitControls damps rotation/pan, but applies wheel dolly immediately. */
export function createSmoothZoom(canvas: HTMLCanvasElement, camera: PerspectiveCamera, controls: {
  target: Vector3; enabled: boolean; enableZoom: boolean; zoomSpeed: number; minDistance: number; maxDistance: number;
}, onInput: () => void, reducedMotion: () => boolean) {
  let target: number | null = null;
  function cancel() { target = null; }
  function wheel(event: WheelEvent) {
    if (!controls.enabled || !controls.enableZoom || !Number.isFinite(event.deltaY) || event.deltaY === 0) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    onInput();
    const pixels = event.deltaY * (event.deltaMode === 1 ? 20 : event.deltaMode === 2 ? canvas.clientHeight : 1)
      * (event.ctrlKey ? 10 : 1);
    const current = camera.position.distanceTo(controls.target);
    target = Math.min(controls.maxDistance, Math.max(controls.minDistance,
      (target ?? current) * Math.pow(0.95, -pixels * controls.zoomSpeed / 100)));
  }
  canvas.addEventListener('wheel', wheel, { capture: true, passive: false });
  canvas.addEventListener('pointerdown', cancel, true);
  return {
    cancel,
    update(dt: number) {
      if (target === null) return;
      if (!controls.enabled || !controls.enableZoom) { cancel(); return; }
      const offset = camera.position.clone().sub(controls.target);
      const radius = offset.length();
      if (radius <= 0) { cancel(); return; }
      const alpha = reducedMotion() ? 1 : 1 - Math.exp(-18 * Math.min(0.1, Math.max(0, dt)));
      const next = radius + (target - radius) * alpha;
      const settled = Math.abs(next - target) <= Math.max(1e-6, target * 1e-4);
      camera.position.copy(controls.target).add(offset.multiplyScalar((settled ? target : next) / radius));
      if (settled) target = null;
    },
    dispose() {
      cancel();
      canvas.removeEventListener('wheel', wheel, true);
      canvas.removeEventListener('pointerdown', cancel, true);
    },
  };
}
