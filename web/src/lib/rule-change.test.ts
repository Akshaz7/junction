import { describe, expect, it } from 'vitest'
import { ruleChangeCard } from './rule-change'
import type { ChangeEntry, RuleChangeEntry } from './types'

const rule: RuleChangeEntry = {
  id: 'rule-demo', type: 'rule_change', doc_a: null, doc_b: null,
  created_at: '2026-11-14T06:30:00Z',
  summary: { kind: 'rule_change', title: 'Access rule — generated for demo', url: 'https://example.org/rules/access',
    summary: 'Source text changed (generated for demo).', detected_at: '2026-11-14T08:00:00+02:00' },
}

describe('rule change feed cards', () => {
  it('maps source metadata and prefers detection time over insertion time', () => {
    expect(ruleChangeCard(rule)).toEqual({ id: rule.id, title: rule.summary!.title,
      url: rule.summary!.url, detail: rule.summary!.summary, detectedAt: '2026-11-14T06:00:00.000Z' })
  })

  it('leaves drawing revisions and new documents out of rule cards', () => {
    const drawing: ChangeEntry = { id: 'drawing-demo', type: 'new_version', doc_a: 'demo@v1', doc_b: 'demo@v2',
      created_at: rule.created_at!, summary: { title: 'Drawing — generated for demo' } }
    expect(ruleChangeCard(drawing)).toBeNull()
    expect(ruleChangeCard({ ...drawing, type: 'new_document' })).toBeNull()
  })

  it('handles missing metadata and falls back from invalid detection time', () => {
    expect(ruleChangeCard({ ...rule, summary: null, created_at: undefined })).toEqual({
      id: rule.id, title: 'Untitled rule source', url: null, detail: '', detectedAt: null,
    })
    expect(ruleChangeCard({ ...rule, summary: undefined })?.detectedAt).toBe('2026-11-14T06:30:00.000Z')
    expect(ruleChangeCard({ ...rule, summary: { title: ' ', summary: '', headline: 'Source changed', detected_at: 'invalid' } }))
      .toMatchObject({ title: 'Untitled rule source', detail: 'Source changed', detectedAt: '2026-11-14T06:30:00.000Z' })
    expect(ruleChangeCard({ ...rule, created_at: 'invalid', summary: {} })?.detectedAt).toBeNull()
  })

  it.each(['javascript:alert(1)', 'data:text/html,test', '/relative', 'not a URL', '', null])('omits unusable source links: %s', (url) => {
    expect(ruleChangeCard({ ...rule, summary: { url } })?.url).toBeNull()
  })
})
