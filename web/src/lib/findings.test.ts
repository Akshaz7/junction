import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { FindingsApi, groupFindings, itemEvidence, type AdvisorCard, type Finding } from './findings'
import { viewerEvidence } from './viewer-evidence'
import { answerToVisualise } from '../viewer3d/visualise'
import { AdvisorCardsPanel } from '../components/findings-screen'

describe('findings evidence', () => {
  it('keeps every cited ID in 3D and uses real page coordinates for 2D, including later pages', () => {
    const { answer, citation } = itemEvidence('doc', ['door-001', 'door-002', 'door-001'], 'Check exits.', [{ doc_id: 'doc', page: 2, items: [{ item_id: 'door-002', bbox_px: [10, 20, 30, 40] }, { item_id: 'unrelated', bbox_px: [0, 0, 5, 5] }] }])
    expect(citation.page).toBe(2)
    expect(answer.evidence.boxes).toEqual([{ item_id: 'door-002', page: 2, bbox_px: [10, 20, 30, 40], label: '2' }])
    expect(viewerEvidence(answer, citation).sources.flatMap((source) => source.itemIds).sort()).toEqual(['door-001', 'door-002'])
    expect(answerToVisualise(answer).highlight).toEqual(['door-001', 'door-002'])
    expect(itemEvidence('ifc', ['GUID'], 'Check.', []).answer.evidence.boxes).toEqual([])
  })
  it('groups by explicit severity without changing the input', () => {
    const rows = [{ id: 'i', severity: 'info' }, { id: 'v', severity: 'violation' }] as Finding[]
    expect(groupFindings(rows).map((group) => [group.label, group.findings.map((row) => row.id)])).toEqual([['Violations', ['v']], ['Suggestions', []], ['Information', ['i']]])
    expect(rows[0].id).toBe('i')
  })
  it('never renders unsourced advisor content and displays the surviving verbatim source', () => {
    const card: AdvisorCard = { card_id: 'a', kind: 'warning', title: 'Check exits', body: 'Check this door.', item_ids: ['door-001'], source: { type: 'rule', ref: 'exit', title: 'Fire safety', quote: 'Two independent exits.' } }
    const html = renderToStaticMarkup(createElement(AdvisorCardsPanel, { cards: [card, { ...card, card_id: 'bad', title: 'Unsourced claim', source: undefined } as unknown as AdvisorCard], onShowItems: () => {} }))
    expect(html).toContain('Fire safety')
    expect(html).toContain('Two independent exits.')
    expect(html).not.toContain('Unsourced claim')
  })
})

describe('findings API', () => {
  it('uses the selected document and preserves no_checks rather than claiming success', async () => {
    const api = new FindingsApi(async (path, init) => {
      expect(path).toBe('/api/findings/run')
      expect(JSON.parse(String(init?.body))).toEqual({ doc_id: 'doc' })
      return Response.json({ status: 'no_checks', findings: [] })
    })
    expect(await api.run('doc')).toEqual({ status: 'no_checks', findings: [] })
    await expect(new FindingsApi(async () => new Response('', { status: 503 })).list('doc')).rejects.toThrow('(503)')
  })
})
