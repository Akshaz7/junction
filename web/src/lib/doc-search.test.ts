import { describe, expect, it } from 'vitest'
import { searchDocuments } from './doc-search'

const doc = (doc_id: string, title: string) => ({ doc_id, title, source: 'x', formats: ['pdf'] })

describe('document search ranking', () => {
  const docs = [doc('finna__4f21ac20-b9c3-4d7e', 'Harbour street elevations'), doc('ifc_bench__ac20-arc', 'AC20 Institute / Phantasy Office Building'), doc('cubicasa__ac-2', 'Floor plan')]
  it('puts title and id word matches above id substrings', () => {
    expect(searchDocuments(docs, 'AC20').map((d) => d.doc_id)).toEqual(['ifc_bench__ac20-arc', 'finna__4f21ac20-b9c3-4d7e'])
  })
  it('exact id wins and non matches drop out', () => {
    expect(searchDocuments(docs, 'ifc_bench__ac20-arc')[0].doc_id).toBe('ifc_bench__ac20-arc')
    expect(searchDocuments(docs, 'zzz')).toEqual([])
  })
})
