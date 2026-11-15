// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { layerOf, PlanLayerChips, PlanLayerShapes, usePlanLayers, type LayerItem, type LayerKey } from './plan-layers'

const items: LayerItem[] = [
  { id: 'wall-001', kind: 'wall', bbox: [0, 0, 100, 10] },
  { id: 'wall-002', kind: 'wall', bbox: [0, 0, 10, 100], polygon: [[0, 0], [10, 0], [10, 100], [0, 100]] },
  { id: 'door-001', kind: 'door', bbox: [20, 0, 30, 10] },
  { id: 'room-001', kind: 'room', bbox: [0, 0, 100, 100], polygon: [[0, 0], [100, 0], [100, 100]] },
  { id: 'toilet-001', kind: 'toilet', bbox: [50, 50, 60, 60], polygon: [[1, 1], [2, 2]] },
  { id: 'sink-001', kind: 'sink', bbox: [70, 70, 80, 80] },
]

let host: HTMLDivElement
let root: Root
function memoryStorage(): Storage {
  const m = new Map<string, string>()
  return { getItem: k => m.get(k) ?? null, setItem: (k, v) => void m.set(k, String(v)), removeItem: k => void m.delete(k), clear: () => m.clear(),
    key: i => [...m.keys()][i] ?? null, get length() { return m.size } }
}
beforeEach(() => { vi.stubGlobal('localStorage', memoryStorage()); Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true }); host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host) })
afterEach(async () => { await act(async () => root.unmount()); host.remove(); localStorage.clear(); vi.unstubAllGlobals() })

describe('plan layers', () => {
  it('maps kinds onto layers', () => {
    expect(['door', 'window', 'wall', 'room', 'text'].map(layerOf)).toEqual(['door', 'window', 'wall', 'room', 'text'])
    expect(layerOf('toilet')).toBe('fixture')
    expect(layerOf('stairs')).toBe('fixture')
    expect(layerOf('Door')).toBe('door')
  })

  it('shows chips with counts, hides empty layers, and toggles', async () => {
    const onToggle = vi.fn()
    await act(async () => root.render(<PlanLayerChips items={items} shown={new Set<LayerKey>(['wall'])} onToggle={onToggle} />))
    const chips = [...host.querySelectorAll('button')]
    expect(chips.map((b) => b.textContent)).toEqual(['Walls 2', 'Doors 1', 'Rooms 1', 'Fixtures 2'])
    expect(chips[0].getAttribute('aria-pressed')).toBe('true')
    expect(chips[1].getAttribute('aria-pressed')).toBe('false')
    await act(async () => chips[3].click())
    expect(onToggle).toHaveBeenCalledWith('fixture')
    await act(async () => root.render(<PlanLayerChips items={[]} shown={new Set()} onToggle={onToggle} />))
    expect(host.querySelector('button')).toBeNull()
    await act(async () => root.render(<PlanLayerChips items={[]} shown={new Set<LayerKey>(['text'])} onToggle={onToggle} />))
    expect(host.textContent).toBe('Text 0')
  })

  it('draws polygons or rects only for shown layers', async () => {
    await act(async () => root.render(<svg><PlanLayerShapes items={items} shown={new Set<LayerKey>(['wall', 'fixture'])} selectedId="sink-001" /></svg>))
    const ids = [...host.querySelectorAll('[data-item-id]')].map((el) => `${el.tagName}:${el.getAttribute('data-item-id')}`)
    expect(ids.sort()).toEqual(['polygon:wall-002', 'rect:sink-001', 'rect:toilet-001', 'rect:wall-001'])
    const wall = host.querySelector('[data-item-id="wall-001"]')!
    expect([wall.getAttribute('x'), wall.getAttribute('width'), wall.getAttribute('height')]).toEqual(['0', '100', '10'])
    expect(host.querySelector('[data-item-id="sink-001"]')!.classList.contains('is-selected')).toBe(true)
    await act(async () => root.render(<svg><PlanLayerShapes items={items} shown={new Set()} /></svg>))
    expect(host.querySelector('[data-testid="plan-layers"]')).toBeNull()
  })

  it('persists the shown set in localStorage', async () => {
    let api: ReturnType<typeof usePlanLayers> | undefined
    function Probe() { api = usePlanLayers(); return null }
    await act(async () => root.render(<Probe />))
    await act(async () => api!.toggle('door'))
    expect(JSON.parse(localStorage.getItem('plan-layers')!)).toEqual(['door'])
    await act(async () => root.unmount())
    root = createRoot(host)
    await act(async () => root.render(<Probe />))
    expect([...api!.shown]).toEqual(['door'])
    await act(async () => api!.clear())
    expect(api!.shown.size).toBe(0)
  })
})
