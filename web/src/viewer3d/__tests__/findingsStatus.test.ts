import { describe, expect, it } from 'vitest';
import { findingsStatus } from '../FindingsPanel';
import type { Finding } from '../findings';

const f = { id: 'a', doc_id: 'd', rule_id: 'r', item_ids: ['door-011'], severity: 'violation', message: 'm', detail: {}, rule: { id: 'r', text: 't' } } as Finding;

describe('findings status line', () => {
  it('shows the server reason when nothing could be checked', () => {
    expect(findingsStatus({ status: 'no_checks', detail: 'Rule checks need an IFC model.', findings: [] }, true)).toBe('Rule checks need an IFC model.');
  });
  it('says what a run checked, on how many items, with unsaved edits and a time', () => {
    const text = findingsStatus({ status: 'ok', findings: [f], checked: ['fi-fire-exits-per-storey'], items_checked: 85,
      edited: true, hidden: 1, checked_at: '2026-11-15T08:00:00Z' }, true);
    expect(text).toMatch(/^Checked 1 rule on 85 items \(your 1 unsaved removal applied\) at .+: 1 finding\.$/);
    expect(findingsStatus({ status: 'ok', findings: [], checked: ['a', 'b'], items_checked: 1 }, true)).toBe('Checked 2 rules on 1 item: no rule problems found.');
  });
  it('does not claim a run happened when only saved findings were loaded', () => {
    expect(findingsStatus({ findings: [] }, false)).toContain('Press Run checks');
    expect(findingsStatus({ findings: [f] }, false)).toBe('');
  });
});
