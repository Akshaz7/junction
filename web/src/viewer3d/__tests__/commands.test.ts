import { describe, expect, it } from 'vitest';
import { applyCommand, applyState, emptyCommandState, readCommandState } from '../commands';

describe('ordered scene command reducer', () => {
  it('highlights replace the previous selection and preserve label and ID order', () => {
    const initial = emptyCommandState();
    const first = applyCommand(initial, { op: 'highlight', item_ids: ['b', 'a', 'b'], labels: { b: 'W2', a: 'W1' } });
    expect([...first.highlighted]).toEqual([['b', 'W2'], ['a', 'W1']]);
    const next = applyCommand(first, { op: 'highlight', item_ids: ['c'] });
    expect([...next.highlighted]).toEqual([['c', 'c']]);
    expect(initial.highlighted.size).toBe(0);
    expect(first.highlighted.size).toBe(2);
  });

  it('hide removes labels, restore after hide restores only requested items, and empty restore restores all', () => {
    const highlighted = applyCommand(emptyCommandState(), { op: 'highlight', item_ids: ['a', 'b'] });
    const hidden = applyCommand(highlighted, { op: 'hide', item_ids: ['a', 'b', 'a'] });
    expect(readCommandState(hidden)).toEqual({ hidden: ['a', 'b'], highlighted: {}, isolated: null });
    const restored = applyCommand(hidden, { op: 'restore', item_ids: ['a'] });
    expect([...restored.hidden]).toEqual(['b']);
    expect([...hidden.hidden]).toEqual(['a', 'b']);
    expect(applyCommand(restored, { op: 'restore', item_ids: [] }).hidden.size).toBe(0);
    expect(applyCommand(restored, { op: 'hide', item_ids: ['a'] }).hidden.has('a')).toBe(true);
  });

  it('isolate restores and highlights targets, hide removes isolated targets, and reset clears every layer', () => {
    const hidden = applyCommand(emptyCommandState(), { op: 'hide', item_ids: ['a', 'b'] });
    const isolated = applyCommand(hidden, { op: 'isolate', item_ids: ['a'], labels: { a: 'W1' } });
    expect(readCommandState(isolated)).toEqual({ hidden: ['b'], highlighted: { a: 'W1' }, isolated: ['a'] });
    expect(readCommandState(applyCommand(isolated, { op: 'hide', item_ids: ['a'] })))
      .toEqual({ hidden: ['b', 'a'], highlighted: {}, isolated: [] });
    expect(readCommandState(applyCommand(isolated, { op: 'reset', item_ids: [] })))
      .toEqual({ hidden: [], highlighted: {}, isolated: null });
    expect([...isolated.isolated!]).toEqual(['a']);
  });

  it('snapshots replace prior state and own their collections', () => {
    const snapshot = { hidden: ['a'], highlighted: ['b', 'c'], labels: { b: 'W2' }, isolated: ['b'] };
    const state = applyState(snapshot);
    snapshot.hidden.push('c'); snapshot.labels.b = 'changed'; snapshot.isolated.push('c');
    expect(readCommandState(state)).toEqual({ hidden: ['a'], highlighted: { b: 'W2', c: 'c' }, isolated: ['b'] });
    expect(applyState({ hidden: [], highlighted: [], labels: {} }).isolated).toBeNull();
  });
});
