// @vitest-environment jsdom
import { act, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { describe, expect, it } from 'vitest'
import { MeasureLayer, useMeasure } from './measure-layer'
import type { Pt } from '../../lib/measure'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })

async function renderSvg(node: ReactNode) {
  const host = document.createElement('div')
  const root = createRoot(host)
  await act(async () => root.render(<svg viewBox="0 0 1000 1000">{node}</svg>))
  return { host, unmount: () => act(async () => root.unmount()) }
}

describe('MeasureLayer', () => {
  it('renders a distance label with non-scaling lines and no pointer events', async () => {
    const { host, unmount } = await renderSvg(<MeasureLayer mode="distance" points={[[0, 0], [300, 400]]} cursor={null} mPerPx={0.01} scale={2} />)
    expect(host.textContent).toContain('5.00 m')
    expect(host.querySelector('polyline')?.getAttribute('vector-effect')).toBe('non-scaling-stroke')
    expect(host.querySelector('g')?.getAttribute('pointer-events')).toBe('none')
    expect(host.querySelector('text')?.getAttribute('font-size')).toBe('6.5')
    expect(host.querySelectorAll('circle')).toHaveLength(2)
    await unmount()
  })
  it('shows area and perimeter for a polygon', async () => {
    const { host, unmount } = await renderSvg(<MeasureLayer mode="area" points={[[0, 0], [100, 0], [100, 100], [0, 100]]} cursor={null} mPerPx={0.01} scale={1} />)
    expect(host.textContent).toContain('1.00 m²')
    expect(host.textContent).toContain('perimeter 4.00 m')
    await unmount()
  })
  it('says there is no scale instead of inventing a number', async () => {
    const { host, unmount } = await renderSvg(<MeasureLayer mode="distance" points={[[0, 0]]} cursor={[300, 400]} mPerPx={null} scale={1} />)
    expect(host.textContent).toBe('No scale on this drawing')
    await unmount()
  })
  it('renders nothing without points', async () => {
    const { host, unmount } = await renderSvg(<MeasureLayer mode="area" points={[]} cursor={[1, 1]} mPerPx={0.01} scale={1} />)
    expect(host.querySelector('g')).toBeNull()
    await unmount()
  })
})

describe('useMeasure', () => {
  async function mountHook(mPerPx: number | null) {
    const ref: { current: ReturnType<typeof useMeasure> | null } = { current: null }
    function Probe() { ref.current = useMeasure(mPerPx); return null }
    const host = document.createElement('div')
    const root = createRoot(host)
    await act(async () => root.render(<Probe />))
    const run = (fn: (m: ReturnType<typeof useMeasure>) => void) => act(async () => fn(ref.current!))
    return { ref, run, unmount: () => act(async () => root.unmount()) }
  }

  it('completes a distance after two points and restarts on the third', async () => {
    const { ref, run, unmount } = await mountHook(0.01)
    await run((m) => m.add([0, 0]))
    expect(ref.current!.mode).toBeNull()
    expect(ref.current!.points).toEqual([])
    await run((m) => m.start('distance'))
    await run((m) => m.add([0, 0]))
    await run((m) => m.move([10, 10]))
    expect(ref.current!.cursor).toEqual([10, 10])
    expect(ref.current!.result).toBeNull()
    await run((m) => m.add([300, 400]))
    expect(ref.current!.result?.distanceM).toBeCloseTo(5)
    expect(ref.current!.cursor).toBeNull()
    await run((m) => m.add([7, 7] as Pt))
    expect(ref.current!.points).toEqual([[7, 7]])
    expect(ref.current!.result).toBeNull()
    await run((m) => m.undo())
    expect(ref.current!.points).toEqual([])
    await run((m) => m.stop())
    expect(ref.current!.mode).toBeNull()
    await unmount()
  })

  it('accumulates area points and finishes on close', async () => {
    const { ref, run, unmount } = await mountHook(0.01)
    await run((m) => m.start('area'))
    await run((m) => { m.add([0, 0]); m.add([100, 0]) })
    await run((m) => m.close())
    expect(ref.current!.result).toBeNull() // fewer than 3 points cannot close
    await run((m) => { m.add([100, 100]); m.add([0, 100]) })
    expect(ref.current!.points).toHaveLength(4)
    await run((m) => m.close())
    expect(ref.current!.result?.areaM2).toBeCloseTo(1)
    expect(ref.current!.result?.perimeterM).toBeCloseTo(4)
    await run((m) => m.clear())
    expect(ref.current!.points).toEqual([])
    expect(ref.current!.mode).toBe('area')
    expect(ref.current!.result).toBeNull()
    await unmount()
  })

  it('gives no result without a scale', async () => {
    const { ref, run, unmount } = await mountHook(null)
    await run((m) => m.start('distance'))
    await run((m) => { m.add([0, 0]); m.add([3, 4]) })
    expect(ref.current!.points).toHaveLength(2)
    expect(ref.current!.result).toBeNull()
    await unmount()
  })
})
