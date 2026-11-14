import { describe, expect, it } from 'vitest'
import { describeMove, friendlyName, planRevision } from './revised-plan'

const size = { w: 400, h: 300 }
const items = [
  { item_id: 'door-001', kind: 'door', tag: 'D12', bbox_px: [10, 20, 40, 30] as [number, number, number, number] },
  { item_id: 'wall-1', kind: 'wall', bbox_px: [100, 100, 200, 110] as [number, number, number, number] },
  { item_id: 'nobox', kind: 'window', bbox_px: null },
]

describe('planRevision', () => {
  it('is empty without edits', () => {
    const p = planRevision({ size, items, removed: [], moved: {}, mPerPx: 0.02 })
    expect(p).toEqual({ erase: [], copies: [], clouds: [], rows: [] })
  })
  it('removed id gives padded erase, cloud and row', () => {
    const p = planRevision({ size, items, removed: ['door-001', 'nobox'], moved: {}, mPerPx: null })
    expect(p.erase).toEqual([[8, 18, 42, 32]])
    expect(p.clouds).toHaveLength(1)
    expect(p.rows).toEqual([{ n: 1, text: 'Door D12 removed' }])
    expect(p.copies).toEqual([])
  })
  it('moved item gives a copy op converted to px', () => {
    const p = planRevision({ size, items, removed: [], moved: { 'wall-1': [0.5, 0] }, mPerPx: 0.05 })
    expect(p.copies).toEqual([{ src: [100, 100, 200, 110], dst: [110, 100, 210, 110] }])
    expect(p.rows[0].text).toBe('Wall moved 0.5 m east')
    expect(p.erase).toHaveLength(1)
  })
  it('skips moves without a scale', () => {
    expect(planRevision({ size, items, removed: [], moved: { 'wall-1': [1, 1] }, mPerPx: null }).rows).toEqual([])
  })
  it('names', () => {
    expect(friendlyName(items[1])).toBe('Wall')
    expect(describeMove(-1, 0.5)).toBe('1.0 m west, 0.5 m south')
  })
})
