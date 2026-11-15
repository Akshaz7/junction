// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { DocumentViewer } from './document-viewer'
import { workspaceApi } from '../lib/api'
import { linkedApi, type LinkedItem } from '../lib/linked'
import type { PlanMap } from '../lib/types'
import { demoDocument, makeDemoAnswer } from '../mock/handler'

vi.setConfig({ testTimeout: 30000 })
vi.mock('./viewer-tools/room-labels', () => ({ RoomLabels: () => null }))

const DOC = demoDocument.doc_id
// A small PDF-like plan map on a 1000x800 page (page pixels).
const planMap: PlanMap = {
  doc_id: DOC, page: 1,
  items: [
    { item_id: 'room-001', kind: 'room', bbox_px: [100, 100, 600, 500], polygon_px: [[100, 100], [600, 100], [600, 500], [100, 500]] },
    // L-shaped wall along the top and left of the room: its bbox covers the whole room, its polygon does not.
    { item_id: 'wall-001', kind: 'wall', bbox_px: [90, 90, 610, 510], polygon_px: [[90, 90], [610, 90], [610, 100], [100, 100], [100, 510], [90, 510]] },
    { item_id: 'door-001', kind: 'door', bbox_px: [300, 450, 360, 500] },
    { item_id: 'text-001', kind: 'text', bbox_px: [320, 250, 400, 280], props: { role: 'room_label' } },
  ],
}

let host: HTMLDivElement
let root: Root
let getItem: ReturnType<typeof vi.fn>

function answer() {
  const value = makeDemoAnswer('How many windows?')
  // The cited window sits inside the room, so a wrongly fired inspect would pick room-001 instead.
  value.evidence.boxes = [{ item_id: 'window-001', page: 1, label: '1', bbox_px: [150, 150, 200, 170] }]
  value.citations = [{ ...value.citations[0], item_ids: ['window-001'] }]
  return value
}

async function render() {
  const value = answer()
  await act(async () => root.render(<DocumentViewer answer={value} citation={value.citations[0]} sheet={false} onClose={() => {}} />))
  const image = host.querySelector('img')!
  Object.defineProperties(image, { naturalWidth: { value: 1000 }, naturalHeight: { value: 800 } })
  await act(async () => image.dispatchEvent(new Event('load')))
  await act(async () => {})
}

const stage = () => host.querySelector<HTMLElement>('[data-testid="drawing-viewport"]')!
/** Client coordinates of a page-pixel point, from the plane's current transform (stage rect is at 0,0 in jsdom). */
function client(px: number, py: number) {
  const plane = host.querySelector<HTMLElement>('.drawing-plane')!
  const match = /translate\((-?[\d.e+-]+)px, (-?[\d.e+-]+)px\) scale\(([\d.e+-]+)\)/.exec(plane.style.transform)!
  const [x, y, scale] = match.slice(1).map(Number)
  return { clientX: x + px * scale, clientY: y + py * scale }
}
function pointer(target: Element, type: string, at: { clientX: number; clientY: number }, pointerType = 'mouse') {
  const event = Object.assign(new MouseEvent(type, { bubbles: true, cancelable: true, button: 0, ...at }), { pointerId: 1, pointerType })
  target.dispatchEvent(event)
}
async function tap(target: Element, at: { clientX: number; clientY: number }, to = at) {
  await act(async () => {
    pointer(target, 'pointerdown', at)
    if (to !== at) pointer(target, 'pointermove', to)
    pointer(target, 'pointerup', to)
    target.dispatchEvent(new MouseEvent('click', { bubbles: true, ...to }))
  })
  await act(async () => {})
}
const panel = () => host.querySelector('[aria-label="Item details"]')
const openedIds = () => getItem.mock.calls.map((call) => call[1])

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addEventListener() {}, removeEventListener() {} })))
  // A 1048x848 stage, so the fitted page scale is ~1 and the pick tolerance is a few page pixels.
  vi.stubGlobal('ResizeObserver', class {
    constructor(private callback: ResizeObserverCallback) {}
    observe(node: HTMLElement) {
      Object.defineProperties(node, { clientWidth: { configurable: true, value: 1048 }, clientHeight: { configurable: true, value: 848 } })
      this.callback([], this as unknown as ResizeObserver)
    }
    disconnect() {}
  })
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => { callback(0); return 0 })
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({})))
  for (const name of ['setPointerCapture', 'releasePointerCapture'] as const) {
    if (!(name in Element.prototype)) Object.defineProperty(Element.prototype, name, { configurable: true, value() {} })
  }
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:drawing') })
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
  vi.spyOn(workspaceApi, 'getDocument').mockResolvedValue(demoDocument)
  vi.spyOn(workspaceApi, 'getPageImage').mockResolvedValue(new Blob())
  vi.spyOn(workspaceApi, 'getDocumentTags').mockResolvedValue({})
  vi.spyOn(workspaceApi, 'getPlanMap').mockResolvedValue(planMap)
  getItem = vi.fn(async (_doc: string, id: string): Promise<LinkedItem> => ({
    item_id: id, kind: id.split('-')[0], tag: id, name: `Name ${id}`, storey: null, type_name: null, props: {}, places: [],
  }))
  vi.spyOn(linkedApi, 'get').mockImplementation(getItem as unknown as typeof linkedApi.get)
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
})

afterEach(async () => {
  await act(async () => root.unmount())
  host.remove()
  vi.restoreAllMocks(); vi.unstubAllGlobals()
})

it('a click on the door opens the item panel for door-001', async () => {
  await render()
  expect(panel()).toBeNull()
  await tap(stage(), client(330, 475))
  expect(panel()).not.toBeNull()
  expect(openedIds()).toEqual(['door-001'])
  expect(getItem.mock.calls[0][0]).toBe(DOC)
  expect(panel()!.querySelector('[data-field="name"]')?.textContent).toBe('Name door-001')
  // The selected item keeps an outline on the plan.
  expect(host.querySelector('[data-testid="plan-pick"][data-item-id="door-001"]')).not.toBeNull()
})

it('a click inside the room away from other items opens room-001, also over its room label', async () => {
  await render()
  await tap(stage(), client(450, 300))
  expect(openedIds()).toEqual(['room-001'])
  expect(panel()!.querySelector('[data-field="name"]')?.textContent).toBe('Name room-001')
  await tap(stage(), client(360, 265))
  expect(openedIds().at(-1)).toBe('room-001')
  // The L-shaped wall is picked on its own polygon, not its room-covering bbox.
  await tap(stage(), client(95, 300))
  expect(openedIds().at(-1)).toBe('wall-001')
})

it('dragging more than 5px pans and opens nothing', async () => {
  await render()
  const start = client(450, 300)
  await tap(stage(), start, { clientX: start.clientX + 20, clientY: start.clientY + 8 })
  expect(panel()).toBeNull()
  expect(getItem).not.toHaveBeenCalled()
})

it('a click on an answer evidence box still opens the cited item, not the room under it', async () => {
  await render()
  const box = host.querySelector('[data-testid="evidence-box-1"]')!
  expect(box.getAttribute('data-item-id')).toBe('window-001')
  await tap(box, client(175, 160))
  expect(openedIds()).toEqual(['window-001'])
  expect(panel()!.querySelector('[data-field="name"]')?.textContent).toBe('Name window-001')
})

it('mouse hover shows a plan-pick outline and marks the stage pickable', async () => {
  await render()
  expect(host.querySelector('[data-testid="plan-pick"]')).toBeNull()
  await act(async () => pointer(stage(), 'pointermove', client(330, 475)))
  const outline = host.querySelector('[data-testid="plan-pick"]')!
  expect(outline.getAttribute('data-item-id')).toBe('door-001')
  expect(outline.querySelector('rect')).not.toBeNull()
  expect(stage().getAttribute('data-pickable')).toBe('true')
  await act(async () => pointer(stage(), 'pointermove', client(450, 300)))
  const room = host.querySelector('[data-testid="plan-pick"]')!
  expect(room.getAttribute('data-item-id')).toBe('room-001')
  expect(room.querySelector('polygon')).not.toBeNull()
  await act(async () => pointer(stage(), 'pointermove', client(900, 700)))
  expect(host.querySelector('[data-testid="plan-pick"]')).toBeNull()
  expect(stage().getAttribute('data-pickable')).toBeNull()
  expect(getItem).not.toHaveBeenCalled()
})
