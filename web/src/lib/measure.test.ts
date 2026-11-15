import { describe, expect, it } from 'vitest'
import { distanceM, formatM, formatM2, perimeterM, polygonAreaM2, snapPoint, type Pt } from './measure'

describe('measure math', () => {
  it('measures a 3-4-5 triangle', () => {
    expect(distanceM([0, 0], [300, 400], 0.01)).toBeCloseTo(5)
    const tri: Pt[] = [[0, 0], [300, 0], [300, 400]]
    expect(perimeterM(tri, 0.01, true)).toBeCloseTo(12)
    expect(perimeterM(tri, 0.01, false)).toBeCloseTo(7)
    expect(polygonAreaM2(tri, 0.01)).toBeCloseTo(6)
  })
  it('measures a unit square regardless of winding', () => {
    const sq: Pt[] = [[0, 0], [100, 0], [100, 100], [0, 100]]
    expect(polygonAreaM2(sq, 0.01)).toBeCloseTo(1)
    expect(polygonAreaM2([...sq].reverse(), 0.01)).toBeCloseTo(1)
    expect(perimeterM(sq, 0.01, true)).toBeCloseTo(4)
    expect(polygonAreaM2(sq.slice(0, 2), 0.01)).toBe(0)
  })
  it('formats metres and square metres', () => {
    expect(formatM(3.4234)).toBe('3.42 m')
    expect(formatM(0.004)).toBe('<1 cm')
    expect(formatM(Number.NaN)).toBe('—')
    expect(formatM2(12.0912)).toBe('12.09 m²')
    expect(formatM2(0.001)).toBe('<0.01 m²')
  })
})

describe('snapPoint', () => {
  const items = [{ bbox: [100, 100, 200, 150] as [number, number, number, number] }, { bbox: [0, 0, 1, 1] as [number, number, number, number], polygon: [[400, 400], [500, 400], [450, 480]] as Pt[] }]
  it('snaps to the nearest bbox corner or polygon vertex', () => {
    expect(snapPoint([203, 147], items, 8)).toEqual([200, 150])
    expect(snapPoint([452, 476], items, 8)).toEqual([450, 480])
  })
  it('snaps to an edge when no corner is near', () => {
    expect(snapPoint([150, 104], items, 8)).toEqual([150, 100])
    expect(snapPoint([196, 125], items, 8)).toEqual([200, 125])
  })
  it('leaves far points alone', () => {
    expect(snapPoint([300, 300], items, 8)).toEqual([300, 300])
    expect(snapPoint([150, 104], [], 8)).toEqual([150, 104])
  })
})
