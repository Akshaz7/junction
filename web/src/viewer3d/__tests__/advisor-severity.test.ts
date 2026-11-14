import { describe, expect, it } from 'vitest';
import { cardSeverity, sourcedCards } from '../advisor';

const card = (extra: Record<string, unknown>) => ({
  card_id: 'c1', kind: 'warning', title: 't', body: 'b', item_ids: ['a'],
  source: { type: 'rule', ref: 'r', title: 'T', quote: 'q' }, ...extra,
});

describe('advisor severity', () => {
  it('uses the explicit severity and keeps checked rule ids', () => {
    const [out] = sourcedCards({ cards: [card({ severity: 'suggestion', checked: ['r1', 'r2'] })] });
    expect(cardSeverity(out)).toBe('suggestion');
    expect(out.checked).toEqual(['r1', 'r2']);
  });
  it('falls back to kind for older cards and ignores unknown severities', () => {
    expect(cardSeverity({ kind: 'warning' })).toBe('violation');
    expect(cardSeverity({ kind: 'option' })).toBe('suggestion');
    expect(cardSeverity({ kind: 'info' })).toBe('info');
    const [out] = sourcedCards({ cards: [card({ severity: 'bogus' })] });
    expect(out.severity).toBeUndefined();
    expect(cardSeverity(out)).toBe('violation');
  });
});
