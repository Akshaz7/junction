import { describe, expect, it } from 'vitest'
import { pickItemAt, pickPlanItem, type PlanPickItem } from './pick-item'

const boxes = [
  { id: 'a', bbox: [0, 0, 100, 10] as [number, number, number, number] },
  { id: 'b', bbox: [0, 0, 10, 100] as [number, number, number, number] },
  { id: 'big', bbox: [0, 0, 100, 100] as [number, number, number, number] },
]
describe('pickItemAt', () => {
  it('picks the smallest box containing the point', () => { expect(pickItemAt([50, 5], boxes, ['a', 'b', 'big'])).toBe('a'); expect(pickItemAt([5, 50], boxes, ['a', 'b', 'big'])).toBe('b') })
  it('only considers the highlight\'s own items', () => { expect(pickItemAt([50, 5], boxes, ['b'])).toBeNull() })
  it('falls back to null when nothing is hit', () => { expect(pickItemAt([500, 500], boxes, ['a', 'b'])).toBeNull() })
  it('uses tolerance for thin walls and prefers the nearest', () => { expect(pickItemAt([50, 14], boxes, ['a', 'b'], 6)).toBe('a'); expect(pickItemAt([50, 14], boxes, ['a', 'b'], 2)).toBeNull() })
})

describe('pickPlanItem', () => {
  const room: PlanPickItem = { id: 'room', kind: 'room', bbox: [0, 0, 200, 200], polygon: [[0, 0], [200, 0], [200, 200], [0, 200]] }
  // L-shaped wall along the top and left edges (10 px thick); its bbox covers the whole room.
  const wall: PlanPickItem = { id: 'wall', kind: 'wall', bbox: [0, 0, 200, 200], polygon: [[0, 0], [200, 0], [200, 10], [10, 10], [10, 200], [0, 200]] }
  const door: PlanPickItem = { id: 'door', kind: 'door', bbox: [50, 0, 80, 20] }
  it('door inside a room picks the door', () => { expect(pickPlanItem([60, 15], [room, wall, door], 2)).toBe('door') })
  it('inside an L-wall bbox but outside its polygon picks the room', () => { expect(pickPlanItem([100, 100], [room, wall], 6)).toBe('room') })
  it('within tolerance of a wall edge picks the wall', () => {
    expect(pickPlanItem([100, 14], [room, wall], 6)).toBe('wall')
    expect(pickPlanItem([5, 100], [room, wall], 6)).toBe('wall')
    expect(pickPlanItem([100, 20], [room, wall], 6)).toBe('room')
  })
  it('wall without polygon uses its bbox grown by tolerance', () => {
    expect(pickPlanItem([100, 14], [{ id: 'w', kind: 'wall', bbox: [0, 0, 200, 10] }], 6)).toBe('w')
  })
  it('nested rooms pick the smaller', () => {
    const inner: PlanPickItem = { id: 'inner', kind: 'room', bbox: [50, 50, 100, 100], polygon: [[50, 50], [100, 50], [100, 100], [50, 100]] }
    expect(pickPlanItem([70, 70], [room, inner], 6)).toBe('inner')
    expect(pickPlanItem([150, 150], [room, inner], 6)).toBe('room')
  })
  it('room needs the point inside its polygon (no tolerance)', () => {
    const tri: PlanPickItem = { id: 'tri', kind: 'room', bbox: [0, 0, 100, 100], polygon: [[0, 0], [100, 0], [0, 100]] }
    expect(pickPlanItem([90, 90], [tri], 6)).toBeNull()
    expect(pickPlanItem([20, 20], [tri], 6)).toBe('tri')
  })
  it('room_label text is ignored', () => {
    const label: PlanPickItem = { id: 'label', kind: 'text', bbox: [90, 90, 130, 105], role: 'room_label' }
    expect(pickPlanItem([100, 100], [label, room], 6)).toBe('room')
  })
  it('a non-label text is picked over a room', () => {
    const note: PlanPickItem = { id: 'note', kind: 'text', bbox: [90, 90, 130, 105], role: 'note' }
    expect(pickPlanItem([100, 100], [room, note], 6)).toBe('note')
  })
  it('nothing hit returns null', () => { expect(pickPlanItem([500, 500], [room, wall, door], 6)).toBeNull() })
  it('invalid bbox is skipped', () => {
    const bad = [
      { id: 'short', kind: 'door', bbox: [0, 0, 300] as unknown as [number, number, number, number] },
      { id: 'nan', kind: 'door', bbox: [0, 0, NaN, 300] as [number, number, number, number] },
    ]
    expect(pickPlanItem([100, 100], [...bad, room], 6)).toBe('room')
  })
  it('handles ~1000 items quickly', () => {
    const many: PlanPickItem[] = []
    for (let i = 0; i < 1000; i++) many.push({ id: `w${i}`, kind: 'wall', bbox: [i, 0, i + 5, 400], polygon: [[i, 0], [i + 5, 0], [i + 5, 400], [i, 400]] })
    const t = performance.now()
    for (let r = 0; r < 100; r++) pickPlanItem([500, 200], many, 2)
    expect((performance.now() - t) / 100).toBeLessThan(50)
  })
})
