// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import {
  distance3, planArea, planPerimeter, useMeasure3D, measure3DStatus, Measure3DOverlay,
  type Measure3D, type P3,
} from '../Measure3D'
import type { Viewer } from '../viewer'

let root: Root, host: HTMLDivElement
beforeEach(() => { (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true; host = document.createElement('div'); document.body.append(host); root = createRoot(host) })
afterEach(() => { act(() => root.unmount()); host.remove() })

/** Minimal renderHook: keeps the latest hook value in `current`. */
function renderMeasure() {
  const ref = { current: null as unknown as Measure3D }
  function Harness() { ref.current = useMeasure3D(); return null }
  act(() => root.render(<Harness />))
  return ref
}
const key = (k: string) => act(() => { window.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true })) })

describe('geometry', () => {
  it('distance3 is the straight 3D line', () => {
    expect(distance3([0, 0, 0], [3, 0, 4])).toBe(5)
    expect(distance3([1, 2, 3], [1, 2, 3])).toBe(0)
    expect(distance3([0, 0, 0], [2, 3, 6])).toBe(7)
  })
  it('planArea uses x/z only', () => {
    expect(planArea([[0, 0, 0], [1, 5, 0], [1, -2, 1], [0, 9, 1]])).toBeCloseTo(1)
    expect(planArea([[0, 0, 1], [0, 0, 0], [1, 0, 0], [1, 0, 1]])).toBeCloseTo(1) // winding does not matter
  })
  it('planPerimeter open vs closed, ignoring y', () => {
    const sq: P3[] = [[0, 0, 0], [1, 7, 0], [1, 0, 1], [0, 3, 1]]
    expect(planPerimeter(sq, false)).toBeCloseTo(3)
    expect(planPerimeter(sq, true)).toBeCloseTo(4)
    expect(planPerimeter([[0, 0, 0], [3, 0, 4]], true)).toBeCloseTo(5) // two points: no closing edge
  })
})

describe('useMeasure3D', () => {
  it('distance: two points finish, a third starts a new measurement', () => {
    const m = renderMeasure()
    act(() => m.current.start('distance'))
    expect(m.current.mode).toBe('distance')
    act(() => m.current.add([0, 0, 0]))
    expect(m.current.done).toBe(false)
    act(() => m.current.add([3, 0, 4]))
    expect(m.current.done).toBe(true)
    expect(m.current.result?.distanceM).toBeCloseTo(5)
    act(() => m.current.add([1, 1, 1]))
    expect(m.current.done).toBe(false)
    expect(m.current.points).toEqual([[1, 1, 1]])
    expect(m.current.result).toBeNull()
  })
  it('hides the cursor once done', () => {
    const m = renderMeasure()
    act(() => m.current.start('distance'))
    act(() => m.current.move([5, 0, 5]))
    expect(m.current.cursor).toEqual([5, 0, 5])
    act(() => m.current.add([0, 0, 0]))
    act(() => m.current.add([1, 0, 0]))
    expect(m.current.cursor).toBeNull()
  })
  it('area: three points + close gives area and perimeter', () => {
    const m = renderMeasure()
    act(() => m.current.start('area'))
    act(() => m.current.add([0, 0, 0]))
    act(() => m.current.add([3, 0, 0]))
    act(() => m.current.close()) // too few points: no-op
    expect(m.current.done).toBe(false)
    act(() => m.current.add([3, 0, 4]))
    expect(m.current.done).toBe(false)
    act(() => m.current.close())
    expect(m.current.done).toBe(true)
    expect(m.current.result?.areaM2).toBeCloseTo(6)
    expect(m.current.result?.perimeterM).toBeCloseTo(12)
  })
  it('Enter closes an area', () => {
    const m = renderMeasure()
    act(() => m.current.start('area'))
    for (const p of [[0, 0, 0], [1, 0, 0], [1, 0, 1]] as P3[]) act(() => m.current.add(p))
    key('Enter')
    expect(m.current.done).toBe(true)
    expect(m.current.result?.areaM2).toBeCloseTo(0.5)
  })
  it('Escape on window cancels', () => {
    const m = renderMeasure()
    act(() => m.current.start('distance'))
    act(() => m.current.add([0, 0, 0]))
    key('Escape')
    expect(m.current.mode).toBeNull()
    expect(m.current.points).toEqual([])
  })
  it('Backspace removes the last point and un-finishes', () => {
    const m = renderMeasure()
    act(() => m.current.start('distance'))
    act(() => m.current.add([0, 0, 0]))
    act(() => m.current.add([1, 0, 0]))
    expect(m.current.done).toBe(true)
    key('Backspace')
    expect(m.current.points).toEqual([[0, 0, 0]])
    expect(m.current.done).toBe(false)
    expect(m.current.result).toBeNull()
  })
  it('keys do nothing when no mode is active', () => {
    const m = renderMeasure()
    key('Escape')
    expect(m.current.mode).toBeNull()
  })
})

describe('measure3DStatus', () => {
  it('prompts and results', () => {
    const m = renderMeasure()
    act(() => m.current.start('distance'))
    expect(measure3DStatus(m.current)).toBe('Click two points on the model · Esc to cancel')
    act(() => m.current.add([0, 0, 0]))
    act(() => m.current.add([3, 0, 4]))
    expect(measure3DStatus(m.current)).toBe('Distance 5.00 m')
    act(() => m.current.start('area'))
    expect(measure3DStatus(m.current)).toBe('Click corners on the model, double-click or Enter to close · Esc to cancel')
    for (const p of [[0, 0, 0], [3, 0, 0], [3, 0, 4]] as P3[]) act(() => m.current.add(p))
    act(() => m.current.close())
    expect(measure3DStatus(m.current)).toBe('Area 6.00 m² · perimeter 12.00 m')
  })
})

describe('Measure3DOverlay', () => {
  const viewer = { projectPoint: (p: P3) => ({ x: p[0] * 10, y: p[2] * 10, visible: true }) } as unknown as Viewer
  function renderOverlay() {
    const ref = { current: null as unknown as Measure3D }
    function Harness() { const m = useMeasure3D(); ref.current = m; return <Measure3DOverlay viewer={viewer} measure={m} /> }
    act(() => root.render(<Harness />))
    return ref
  }
  it('renders nothing without a mode or viewer', () => {
    renderOverlay()
    expect(host.querySelector('[data-testid="measure-3d"]')).toBeNull()
    act(() => root.render(<Measure3DOverlay viewer={null} measure={{ mode: 'distance' } as Measure3D} />))
    expect(host.querySelector('[data-testid="measure-3d"]')).toBeNull()
  })
  it('distance: path, two circles and the label at the midpoint', () => {
    const m = renderOverlay()
    act(() => m.current.start('distance'))
    act(() => m.current.add([0, 0, 0]))
    act(() => m.current.add([3, 0, 4]))
    const svg = host.querySelector('[data-testid="measure-3d"]')!
    expect(svg).not.toBeNull()
    expect(svg.querySelector('path')!.getAttribute('d')).toBe('M0,0 L30,40')
    const circles = svg.querySelectorAll('circle')
    expect(circles).toHaveLength(2)
    expect(circles[1].getAttribute('cx')).toBe('30')
    expect(circles[1].getAttribute('cy')).toBe('40')
    expect(svg.querySelector('text')!.textContent).toBe('5.00 m')
    const label = svg.querySelector('text.measure-label')!
    expect([label.getAttribute('x'), label.getAttribute('y')]).toEqual(['15', '10'])
  })
  it('area: closed path and area label', () => {
    const m = renderOverlay()
    act(() => m.current.start('area'))
    for (const p of [[0, 0, 0], [3, 0, 0], [3, 0, 4]] as P3[]) act(() => m.current.add(p))
    act(() => m.current.close())
    const svg = host.querySelector('[data-testid="measure-3d"]')!
    const path = svg.querySelector('path')!
    expect(path.getAttribute('d')).toBe('M0,0 L30,0 L30,40 Z')
    expect(path.getAttribute('class')).toBe('measure-shape is-closed')
    expect(svg.querySelectorAll('circle')).toHaveLength(3)
    expect(svg.querySelector('text')!.textContent).toBe('6.00 m²')
  })
  it('live distance label from the cursor before the second click', () => {
    const m = renderOverlay()
    act(() => m.current.start('distance'))
    act(() => m.current.add([0, 0, 0]))
    act(() => m.current.move([0, 0, 2]))
    const svg = host.querySelector('[data-testid="measure-3d"]')!
    expect(svg.querySelectorAll('circle')).toHaveLength(2)
    expect(svg.querySelector('text')!.textContent).toBe('2.00 m')
  })
})
