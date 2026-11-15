import { describe, expect, it } from 'vitest'
import { cssMatrix, discipline, floorKey, isOverlayMatch, overlayActionAnswer, overlayAlignedAnswer, overlayRequest, rankOverlaySheets, type OverlayDoc } from './sheet-overlay'

const doc = (id: string, title: string, extra: Partial<OverlayDoc> = {}): OverlayDoc => ({ doc_id: id, title, kind: 'pdf', pages: 1, source: 'uploaded', formats: ['pdf'], licence: '', credit: '', heldout: false, ...extra })
const base = doc('a', 'Floor plan', { project: 'Site', floor: '3' })
const vent = doc('v', 'Ventilation', { project: 'Site', floor: '3' })

describe('overlay candidates for uploaded sheets with no floor metadata', () => {
  const up = { project: 'Uploads', folder: 'Uploads/Reference drawings', discipline: 'Reference drawings' }
  const ark = doc('ark', 'ARK-103-03 floor plan 3rd floor', up)
  const ventU = doc('vent', 'L30301_VENTILATION SYSTEMS_3RD FLOOR_BLOCK U', up)
  const noise = ['Alpha plan', 'Zed 2nd floor ventilation'].map((t, i) => doc(`n${i}`, t, up))
  it('reads the floor from titles in any case and wording', () => {
    expect(floorKey(ark)).toBe('3'); expect(floorKey(ventU)).toBe('3')
    expect(floorKey(doc('l', 'Plan', { floor: 'Level 3' }))).toBe('3')
    expect(floorKey(doc('g', 'Ground floor plan'))).toBe('0'); expect(floorKey(doc('p', 'Plan'))).toBeNull()
  })
  it('offers the ventilation sheet for the architecture sheet and vice versa, first', () => {
    expect(rankOverlaySheets(ark, [...noise, ventU, ark])[0].doc_id).toBe('vent')
    expect(rankOverlaySheets(ventU, [...noise, ark, ventU])[0].doc_id).toBe('ark')
    expect(isOverlayMatch(ark, ventU)).toBe(true); expect(isOverlayMatch(ark, noise[1])).toBe(false)
  })
})

describe('sheet overlay', () => {
  it('ranks same project/floor first without hiding other sheets', () => {
    const other = doc('x', 'A sheet', { project: 'Elsewhere', floor: '3' })
    expect(rankOverlaySheets(base, [other, base, vent]).map((d) => d.doc_id)).toEqual(['v', 'x'])
  })
  it('does not count missing metadata as a floor match', () => {
    const plain = doc('plain', 'Plan')
    expect(rankOverlaySheets(plain, [vent, doc('z', 'A sheet')])[0].doc_id).toBe('z')
  })
  it.each([['Ilmanvaihto', 'Ventilation'], ['Lüftung', 'Ventilation'], ['Sähkö', 'Electrical'], ['Sanitär', 'Plumbing'], ['Rakenne', 'Structure'], ['Brand', 'Fire protection']])('tints multilingual discipline %s', (title, name) => {
    expect(discipline(doc('x', title)).name).toBe(name)
  })
  it('chat opens a unique matching discipline and preserves overlay direction', () => {
    const request = overlayRequest('overlay the ventilation plan on the floor plan', [vent, base], [base])!
    expect(request.base.doc_id).toBe('a'); expect(request.overlay?.doc_id).toBe('v')
  })
  it('chat respects the named base even when only the top discipline is selected', () => {
    expect(overlayRequest('overlay ventilation on the floor plan', [base, vent], [vent])?.base.doc_id).toBe('a')
    const electrical = doc('e', 'Electrical')
    const request = overlayRequest('overlay ventilation on the electrical plan', [vent, electrical], [])!
    expect(request.base.doc_id).toBe('e'); expect(request.overlay?.doc_id).toBe('v')
  })
  it('chat leaves ambiguous matches to the picker', () => {
    const request = overlayRequest('overlay the ventilation plan', [base, vent, doc('v2', 'Ventilation level 2')], [base])!
    expect(request.overlay).toBeNull()
    expect(overlayRequest('Count the windows', [base], [])).toBeNull()
  })
  it('UI action carries source citations and no invented alignment claim', () => {
    const answer = overlayActionAnswer('overlay', base, vent)
    expect(answer.citations.map((c) => c.doc_id)).toEqual(['a', 'v'])
    expect(answer.reasoning?.confidence.pct).toBeNull()
    expect(answer.cost.usd_total).toBe(0)
    expect(answer.answer.value).toBeNull()
  })
  it('reports real anchor consensus separately from measurement accuracy', () => {
    const result = { status: 'aligned' as const, matrix: [[1,0,0],[0,1,0]] as [[number,number,number],[number,number,number]], method: 'similarity', anchor_count: 4, candidate_count: 5, residual_px: .5, residual_mm: 5, detail: 'Aligned on 4 shared labels, ± 5 mm', anchors: [{ label: 'A', base: [10,10] as [number,number], overlay: [10,10] as [number,number], base_bbox: [8,8,12,12] as [number,number,number,number] }], base_image: {w:100,h:100}, overlay_image: {w:100,h:100} }
    const answer = overlayAlignedAnswer(overlayActionAnswer('overlay',base,vent), result, base, vent)
    expect(answer.reasoning?.confidence.pct).toBeNull()
    expect(answer.reasoning?.confidence.reason).toContain('4 of 5 candidate anchors')
    expect(answer.reasoning?.confidence.reason).toContain('not measurement accuracy')
    expect(answer.evidence.boxes[0].bbox_px).toEqual([8,8,12,12])
    expect(answer.citations).toHaveLength(2)
  })
  it('uses the correct CSS matrix column order for rotated sheets', () => {
    expect(cssMatrix([[0,-2,10],[2,0,20]])).toBe('matrix(0,2,-2,0,10,20)')
  })
})
