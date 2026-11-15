// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { Layers3D, groupSceneItems } from '../Layers3D';
import type { Viewer } from '../viewer';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const items = {
  w1: { kind: 'wall' }, w2: { kind: 'curtain_wall' }, d1: { kind: 'door' }, s1: { kind: 'slab' },
  r1: { kind: 'room' }, t1: { kind: 'toilet' }, c1: { kind: 'column' },
};
const scene = { manifest: { items } };
let host: HTMLDivElement, root: Root;
let notify: () => void;
const setLayerHidden = vi.fn();
const viewer = () => ({
  scene, setLayerHidden,
  onCutawayChange(cb: () => void) { notify = cb; return () => {}; },
}) as unknown as Viewer;

beforeEach(() => { host = document.createElement('div'); document.body.append(host); root = createRoot(host); setLayerHidden.mockClear(); });
afterEach(() => { act(() => root.unmount()); host.remove(); });

it('groups manifest kinds into 3D layers', () => {
  const g = groupSceneItems(scene as never);
  expect(g.get('wall')).toEqual(['w1', 'w2']);
  expect(g.get('floor')).toEqual(['s1', 'r1']);
  expect(g.get('fixture')).toEqual(['t1']);
  expect(g.get('structure')).toEqual(['c1']);
});

it('shows chips with counts, all on, and toggling hides that layer visually', () => {
  act(() => root.render(<Layers3D viewer={viewer()} />));
  const chips = [...host.querySelectorAll<HTMLButtonElement>('[data-layer]')];
  expect(chips.map((c) => c.textContent)).toEqual(['Walls 2', 'Doors 1', 'Rooms/Floors 2', 'Structure 1', 'Fixtures 1']);
  expect(chips.every((c) => c.getAttribute('aria-pressed') === 'true')).toBe(true);
  expect(setLayerHidden).not.toHaveBeenCalled(); // all layers on: the viewer is left untouched
  act(() => chips[0].click());
  expect(setLayerHidden).toHaveBeenLastCalledWith(['w1', 'w2']);
  expect(chips[0].getAttribute('aria-pressed')).toBe('false');
  act(() => chips[2].click());
  expect(setLayerHidden).toHaveBeenLastCalledWith(['w1', 'w2', 's1', 'r1']);
  act(() => chips[0].click());
  expect(setLayerHidden).toHaveBeenLastCalledWith(['s1', 'r1']);
  act(() => notify());
});

it('renders nothing without a viewer or scene', () => {
  act(() => root.render(<Layers3D viewer={null} />));
  expect(host.innerHTML).toBe('');
});
