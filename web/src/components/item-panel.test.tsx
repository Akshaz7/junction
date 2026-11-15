// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { ItemPanel } from './item-panel'
import { linkedApi, type LinkedItem } from '../lib/linked'

const measure = { from: 'pdf_vector', m_per_pt: 0.0352778, scale_source: 'printed 1:100',
  scale_check: { printed_areas_rel_err: 0.0236, fit_n: 17, fit_vs_printed_rel: 0.0169, agree_2pct: true }, geometry: 'polygon' }
const door = { item_id: 'p1-door-4', kind: 'door', tag: null, name: null, storey: 'Ground', type_name: null,
  props: { width_m: 0.96, swing: 'ccw', double: false, leaf: true, width_pt: 27.2, hinge: [1, 2], swing_bbox: [1, 2, 3, 4], measure },
  quantities: { width_m: 0.96, height_m: 2.1 }, wall_details: null, places: [] } as unknown as LinkedItem

afterEach(() => { vi.restoreAllMocks() })

it('shows measured rows, provenance and only the leftover source properties', async () => {
  vi.spyOn(linkedApi, 'get').mockResolvedValue(door)
  const host = document.createElement('div')
  const root = createRoot(host)
  await act(async () => root.render(<ItemPanel docId="plan a" itemId="p1-door-4" sheet={false} onClose={() => {}} onOpenPlace={() => {}} />))
  const measured = [...host.querySelectorAll('.item-measured > div')].map((n) => [n.querySelector('dt')?.textContent, n.querySelector('dd')?.textContent])
  expect(measured).toEqual([['Width', '0.96 m'], ['Height', '2.10 m'], ['Swing', 'Anticlockwise'], ['Double leaf', 'No']])
  expect(host.querySelector('.item-provenance')?.textContent).toBe("Read from the PDF's vector lines at the printed scale 1:100, checked against 17 printed room areas (2.4% off).")
  expect([...host.querySelectorAll('[data-property]')].map((n) => n.getAttribute('data-property'))).toEqual(['leaf'])
  expect(host.textContent).not.toContain('m_per_pt')
  expect(host.querySelector('[data-field="storey"]')?.textContent).toBe('Ground')
  const ask = host.querySelector<HTMLAnchorElement>('a.item-ask')!
  expect(ask.classList.contains('wall-ask')).toBe(false)
  expect(new URLSearchParams(ask.getAttribute('href')!.split('?')[1]).get('question')).toBe('Tell me about door p1-door-4: its size and where it is.')
  await act(async () => root.unmount())
})

it('keeps the wall ask link for walls', async () => {
  vi.spyOn(linkedApi, 'get').mockResolvedValue({ ...door, kind: 'wall', tag: 'W2', props: { thickness_m: 0.268, length_m: 10.567, style: 'fill' } } as LinkedItem)
  const host = document.createElement('div')
  const root = createRoot(host)
  await act(async () => root.render(<ItemPanel docId="plan a" itemId="w" sheet={false} onClose={() => {}} onOpenPlace={() => {}} />))
  const ask = host.querySelector<HTMLAnchorElement>('a.wall-ask.item-ask')!
  expect(ask.textContent).toBe('Ask about this wall')
  expect(new URLSearchParams(ask.getAttribute('href')!.split('?')[1]).get('question')).toContain('wall W2')
  expect(host.querySelector('.item-provenance')).toBeNull()
  expect(host.textContent).toContain('10.57 m')
  await act(async () => root.unmount())
})
