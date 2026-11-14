import { afterEach, describe, expect, it, vi } from 'vitest';
import { PerspectiveCamera, Vector3 } from 'three';
import { clearViewerHighlights, itemsOfPickedKind } from '../selection';
import { applyCommand, emptyCommandState } from '../commands';
import { getLinkedItem, setHover, setSelected } from '../link';
import { frameThrottle } from '../frameThrottle';
import { createSmoothZoom } from '../smoothZoom';
import type { SceneManifest } from '../scene';

afterEach(() => { vi.unstubAllGlobals(); });

describe('clear highlights and Shift-click selection', () => {
  it('clears answer/linked highlights without restoring removed items or leaving isolation', () => {
    let state = applyCommand(emptyCommandState(), { op: 'hide', item_ids: ['removed'] });
    state = applyCommand(state, { op: 'isolate', item_ids: ['door-a', 'door-b'] });
    setHover('door-a', '2d'); setSelected('door-b', '3d');
    clearViewerHighlights({ applyCommand(command) { state = applyCommand(state, command); } });
    expect([...state.hidden]).toEqual(['removed']);
    expect([...state.highlighted]).toEqual([]);
    expect([...state.isolated!]).toEqual(['door-a', 'door-b']);
    expect(getLinkedItem()).toMatchObject({ hovered: null, selected: null });
  });

  it('selects every item of the picked kind on unseen models, across storeys', () => {
    const manifest = { items: {
      'unseen-a': { kind: 'door', tag: 'D9', storey: 'Ground' },
      'unseen-b': { kind: 'window', tag: 'D10', storey: 'Ground' },
      'unseen-c': { kind: 'door', tag: 'arbitrary-mark', storey: 'First' },
    } } as unknown as SceneManifest;
    expect(itemsOfPickedKind(manifest, 'unseen-a')).toEqual(['unseen-a', 'unseen-c']);
    expect(itemsOfPickedKind(manifest, 'missing')).toEqual([]);
    expect(itemsOfPickedKind(manifest, 'unseen-b')).toEqual(['unseen-b']);
  });
});

it('applies only the latest slider position per animation frame and cancels on disposal', () => {
  const frames = new Map<number, FrameRequestCallback>();
  let next = 0;
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => { frames.set(++next, callback); return next; });
  vi.stubGlobal('cancelAnimationFrame', (id: number) => frames.delete(id));
  const apply = vi.fn();
  const scrub = frameThrottle(apply);
  scrub.schedule(1.1); scrub.schedule(1.2); scrub.schedule(1.8);
  expect(frames.size).toBe(1); expect(apply).not.toHaveBeenCalled();
  const callback = frames.get(1)!; frames.delete(1); callback(16);
  expect(apply.mock.calls).toEqual([[1.8]]);
  scrub.schedule(2.5); scrub.cancel();
  expect(frames.size).toBe(0); expect(apply).toHaveBeenCalledOnce();
});

function zoomFixture() {
  const canvas = Object.assign(new EventTarget(), { clientHeight: 600 }) as HTMLCanvasElement;
  const camera = new PerspectiveCamera(); camera.position.set(0, 0, 10);
  const controls = { target: new Vector3(), enabled: true, enableZoom: true, zoomSpeed: 1, minDistance: 2, maxDistance: 20 };
  const input = vi.fn();
  let reduced = false;
  const zoom = createSmoothZoom(canvas, camera, controls, input, () => reduced);
  const wheel = (deltaY: number) => {
    const event = new Event('wheel', { cancelable: true });
    Object.assign(event, { deltaY, deltaMode: 0, ctrlKey: false });
    canvas.dispatchEvent(event); return event;
  };
  return { canvas, camera, controls, input, zoom, wheel, reduce() { reduced = true; } };
}

describe('damped camera zoom', () => {
  it('approaches the wheel target smoothly over frames, preserves direction, and clamps distance', () => {
    const { camera, zoom, wheel, input } = zoomFixture();
    expect(wheel(-100).defaultPrevented).toBe(true);
    expect(input).toHaveBeenCalledOnce();
    expect(camera.position.z).toBe(10);
    zoom.update(1 / 60);
    expect(camera.position.z).toBeLessThan(10); expect(camera.position.z).toBeGreaterThan(9.5);
    const first = camera.position.z;
    zoom.update(1 / 60); expect(camera.position.z).toBeLessThan(first);
    for (let i = 0; i < 120; i++) zoom.update(1 / 60);
    expect(camera.position.z).toBeCloseTo(9.5, 4);
    wheel(100_000); for (let i = 0; i < 120; i++) zoom.update(1 / 60);
    expect(camera.position.z).toBeCloseTo(20, 8);
    expect(camera.position.x).toBe(0); expect(camera.position.y).toBe(0);
    zoom.dispose();
  });

  it('honours reduced motion, cancels on pointer input, and releases listeners', () => {
    const { canvas, camera, controls, zoom, wheel, reduce, input } = zoomFixture();
    reduce(); wheel(-100); zoom.update(1 / 60);
    expect(camera.position.z).toBeCloseTo(9.5, 8);
    wheel(-100); canvas.dispatchEvent(new Event('pointerdown')); zoom.update(1 / 60);
    expect(camera.position.z).toBeCloseTo(9.5, 8);
    controls.enabled = false;
    expect(wheel(-100).defaultPrevented).toBe(false);
    const calls = input.mock.calls.length;
    zoom.dispose(); controls.enabled = true; wheel(-100); zoom.update(1 / 60);
    expect(input).toHaveBeenCalledTimes(calls); expect(camera.position.z).toBeCloseTo(9.5, 8);
  });
});
