import { describe, expect, it } from 'vitest'
import { pickItemAt } from './pick-item'

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
