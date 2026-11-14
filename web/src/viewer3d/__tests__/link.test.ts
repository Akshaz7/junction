// @vitest-environment node
import { createElement } from 'react';
import { renderToString } from 'react-dom/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getLinkedItem, setHover, setSelected, subscribe, useLinkedItem } from '../link';

beforeEach(() => {
  setHover(null, '2d');
  setHover(null, '3d');
  setSelected(null, '2d');
});

describe('linked 2D/3D item selection', () => {
  it('publishes hover and selection independently with their originating view', () => {
    const received = vi.fn();
    const stop = subscribe(received);
    setHover('window-003', '2d');
    setSelected('door-001', '3d');
    expect(received).toHaveBeenCalledTimes(2);
    expect(received.mock.calls[0][0]).toEqual({
      hovered: 'window-003', hoverSource: '2d', selected: null, selectedSource: null,
    });
    expect(getLinkedItem()).toEqual({
      hovered: 'window-003', hoverSource: '2d', selected: 'door-001', selectedSource: '3d',
    });
    stop();
  });

  it('retains selection after hover leaves and protects the other view from late leaves', () => {
    setHover('window-003', '2d');
    setSelected('window-003', '2d');
    setHover('door-001', '3d');
    setHover(null, '2d');
    expect(getLinkedItem().hovered).toBe('door-001');
    setHover(null, '3d');
    expect(getLinkedItem()).toEqual({
      hovered: null, hoverSource: null, selected: 'window-003', selectedSource: '2d',
    });
    setSelected(null, '3d');
    expect(getLinkedItem().selected).toBeNull();
    expect(getLinkedItem().selectedSource).toBeNull();
  });

  it('deduplicates pointer moves, keeps snapshots stable, and allows a new source for the same ID', () => {
    const received = vi.fn();
    const stop = subscribe(received);
    const initial = getLinkedItem();
    setSelected(null, '3d');
    expect(getLinkedItem()).toBe(initial);
    setHover('window-003', '2d');
    const hovered = getLinkedItem();
    setHover('window-003', '2d');
    expect(getLinkedItem()).toBe(hovered);
    expect(Object.isFrozen(hovered)).toBe(true);
    setHover('window-003', '3d');
    expect(received).toHaveBeenCalledTimes(2);
    expect(getLinkedItem().hoverSource).toBe('3d');
    stop();
    setHover(null, '3d');
    expect(received).toHaveBeenCalledTimes(2);
  });

  it('lets the receiving view filter its own echoes without losing updates from the other view', () => {
    const selected2d: (string | null)[] = [];
    const selected3d: (string | null)[] = [];
    const stop2d = subscribe((state) => { if (state.selectedSource === '3d') selected2d.push(state.selected); });
    const stop3d = subscribe((state) => { if (state.selectedSource === '2d') selected3d.push(state.selected); });
    setSelected('window-003', '2d');
    setSelected('door-001', '3d');
    expect(selected2d).toEqual(['door-001']);
    expect(selected3d).toEqual(['window-003']);
    stop2d(); stop3d();
  });

  it('makes the same snapshot available through the React hook', () => {
    setSelected('window-003', '2d');
    function Probe() {
      const item = useLinkedItem();
      return createElement('output', null, `${item.selected}:${item.selectedSource}`);
    }
    expect(renderToString(createElement(Probe))).toBe('<output>window-003:2d</output>');
  });
});
