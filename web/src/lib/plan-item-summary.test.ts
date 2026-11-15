import { describe, expect, it } from 'vitest'
import { planItemSummary } from './plan-item-summary'

const B: [number, number, number, number] = [0, 0, 100, 10]

describe('planItemSummary', () => {
  it('summarises real PDF plan-map props', () => {
    expect(planItemSummary({ id: 'wall-001', kind: 'wall', props: { thickness_m: 0.268, length_m: 10.567 }, bbox: B })).toBe('Wall · 10.57 m long · 0.27 m thick')
    expect(planItemSummary({ id: 'door-001', kind: 'door', props: { width_m: 0.96, swing: 'cw', double: false }, bbox: B })).toBe('Door · 0.96 m wide · swings clockwise')
    expect(planItemSummary({ id: 'window-001', kind: 'window', props: { width_m: 1.11 }, bbox: B })).toBe('Window · 1.11 m')
    expect(planItemSummary({ id: 'room-001', kind: 'room', label: 'Pièce', props: { room_type: 'other', number: '2.01', area_m2: 12.09, area_m2_label: 12.09, area_m2_geom: 11.48 }, bbox: B })).toBe('Room 2.01 Pièce · 12.09 m²')
    expect(planItemSummary({ id: 'text-001', kind: 'text', label: 'Pièce', props: { role: 'room_label' }, bbox: B })).toBe('Room label · “Pièce”')
    expect(planItemSummary({ id: 'toilet-001', kind: 'wc', bbox: B })).toBe('Toilet')
    expect(planItemSummary({ id: 'bathtub-001', kind: 'bathtub', bbox: B })).toBe('Bathtub')
  })
  it('falls back to bbox × mPerPx for raster items, marked approximate', () => {
    expect(planItemSummary({ id: 'wall-002', kind: 'wall', props: { conf: 0.9 }, bbox: [0, 0, 400, 20] }, 0.01)).toBe('Wall · ≈ 4.00 m long · ≈ 0.20 m thick')
    expect(planItemSummary({ id: 'door-002', kind: 'door', props: { conf: 0.8 }, bbox: [10, 10, 100, 106] }, 0.01)).toBe('Door · ≈ 0.96 m wide')
    expect(planItemSummary({ id: 'toilet-002', kind: 'toilet', bbox: [0, 0, 40, 70] }, 0.01)).toBe('Toilet · ≈ 0.40 × 0.70 m')
  })
  it('shows the kind only without a scale or size props', () => {
    expect(planItemSummary({ id: 'wall-003', kind: 'wall', props: { conf: 0.7 }, bbox: [0, 0, 400, 20] })).toBe('Wall')
    expect(planItemSummary({ id: 'door-003', kind: 'door', bbox: B }, null)).toBe('Door')
    expect(planItemSummary({ id: 'window-003', kind: 'window', bbox: B }, 0)).toBe('Window')
  })
})
