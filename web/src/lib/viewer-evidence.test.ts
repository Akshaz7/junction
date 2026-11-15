import { describe, expect, it } from 'vitest'
import { makeDemoAnswer } from '../mock/handler'
import { viewerEvidence } from './viewer-evidence'

describe('citation to drawing evidence', () => {
  it('navigates only the three cited items among 27 page detections', () => {
    const answer = makeDemoAnswer('How many windows?')
    answer.evidence.boxes = Array.from({ length: 27 }, (_, index) => ({ item_id: `item-${index + 1}`, page: 1, label: String(index + 1), bbox_px: [index, 0, index + 1, 10] }))
    answer.citations[0].item_ids = ['item-4', 'item-12', 'item-22']
    const result = viewerEvidence(answer, { ...answer.citations[0], item_ids: ['item-22'] })
    expect(result.sources.map((source) => source.id)).toEqual(['item-4', 'item-12', 'item-22'])
    expect(result.regions.map((region) => region.id)).toEqual(result.sources.map((source) => source.id))
    expect(result.initial).toBe(2)
  })

  it('keeps all drawing items when there is no cited selection', () => {
    const answer = makeDemoAnswer('How many windows?')
    const citation = { ...answer.citations[0], item_ids: [], bbox_px: null }
    answer.citations = []
    const result = viewerEvidence(answer, citation)
    expect(result.sources).toHaveLength(answer.evidence.boxes.length)
  })

  it('preserves evidence numbering and focuses the cited item instead of the first page item', () => {
    const answer = makeDemoAnswer('How many windows are there?')
    const citation = { ...answer.citations[0], item_ids: ['window-002'] }
    const result = viewerEvidence(answer, citation)
    expect(result.initial).toBe(1)
    expect(result.regions.map((region) => region.label)).toEqual(['1', '2'])
  })

  it('shows text citation bounds and excludes boxes from another document or page', () => {
    const answer = makeDemoAnswer('How many windows are there?')
    const citation = { ...answer.citations[0], n: 3, doc_id: 'other-doc', kind: 'text' as const, item_ids: [], bbox_px: [10, 20, 30, 40] as [number, number, number, number] }
    answer.doc_ids.push('other-doc')
    answer.citations.push(citation)
    const result = viewerEvidence(answer, citation)
    expect(result.regions).toEqual([{ id: 'citation-3', label: '3', bbox: [10, 20, 30, 40], text: true }])
    expect(viewerEvidence(answer, { ...citation, page: 2 }).regions).toEqual([])
  })

  it('counts and selects IFC evidence even without page boxes', () => {
    const answer = makeDemoAnswer('What is the narrowest door width used here?')
    answer.evidence.boxes = []
    answer.evidence.scene.highlight_item_ids = ['ifc-door-1', 'ifc-door-2']
    answer.citations = [{ ...answer.citations[0], kind: 'element', bbox_px: null, item_ids: ['ifc-door-1', 'ifc-door-2'] }]
    const result = viewerEvidence(answer, { ...answer.citations[0], item_ids: ['ifc-door-2'] })
    expect(result.regions).toEqual([])
    expect(result.sources.map((source) => source.itemIds)).toEqual([['ifc-door-1'], ['ifc-door-2']])
    expect(result.sources.every((source) => source.bbox === null)).toBe(true)
    expect(result.initial).toBe(1)
  })

  it('does not count boxed or repeatedly cited elements twice', () => {
    const answer = makeDemoAnswer('How many windows are there?')
    answer.citations.push({ ...answer.citations[0], n: 2 })
    const result = viewerEvidence(answer, answer.citations[0])
    expect(result.sources.map((source) => source.id)).toEqual(result.regions.map((region) => region.id))
  })

  it('keeps cross-sheet boxes on their own document even when pages and item IDs overlap', () => {
    const answer = makeDemoAnswer('How many windows are there?')
    const first = answer.doc_ids[0]
    answer.doc_ids.push('services')
    answer.evidence.boxes = [
      { item_id: 'same-id', doc_id: first, page: 1, label: '1', bbox_px: [10, 20, 30, 40] },
      { item_id: 'same-id', doc_id: 'services', page: 1, label: '2', bbox_px: [100, 200, 300, 400] },
    ]
    answer.citations = [
      { ...answer.citations[0], n: 1, doc_id: first, item_ids: ['same-id'] },
      { ...answer.citations[0], n: 2, doc_id: 'services', item_ids: ['same-id'] },
    ]
    expect(viewerEvidence(answer, answer.citations[0]).regions.map((r) => r.label)).toEqual(['1'])
    expect(viewerEvidence(answer, answer.citations[1]).regions.map((r) => r.label)).toEqual(['2'])
  })
})
