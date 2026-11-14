import { describe, expect, it } from 'vitest'
import { buildRoomLabels } from './room-labels'

describe('room labels', () => {
  it('names rooms from their element and skips unnamed ones', () => {
    const items = [
      { item_id: 'a', kind: 'room', label: '115', bbox_px: [0, 0, 300, 200], props: { area_m2: 18.44 } },
      { item_id: 'b', kind: 'room', label: '116', bbox_px: [0, 0, 300, 200] },
      { item_id: 'c', kind: 'wall', label: 'W1', bbox_px: [0, 0, 5, 5] },
    ]
    const elements = [{ item_id: 'a', kind: 'room', type_name: 'Büroarbeit', props: { long_name: 'Büro' } }, { item_id: 'c', kind: 'wall' }]
    expect(buildRoomLabels(items, elements)).toEqual([{ id: 'a', box: [0, 0, 300, 200], name: 'Büro', detail: '115 · 18.4 m²' }])
    expect(buildRoomLabels(items, [])).toEqual([])
  })
})
