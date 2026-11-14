// @vitest-environment jsdom
// API fixtures generated for demo tests: a design saved twice from 3D edits.
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { CompareScreen } from './compare-screen'
import { workspaceApi } from '../lib/api'

const doc = 'ifc_bench__ac20-arc'
const prefix = `dv:${doc}:`
const entry = (a: number, b: number) => ({ id: `${prefix}${a}-${b}`, type: 'new_version', doc_a: doc, doc_b: doc, created_at: `2026-11-14T1${b}:00:00Z`,
  summary: { doc_id: doc, title: 'AC20', series_id: `design:${doc}`, n_changes: 1, edited: true, index_a: a, index_b: b, pair_prefix: prefix,
    version_a: a ? `Edited version ${a}` : 'Original', version_b: `Edited version ${b}`, headline: 'x' } })
const detail = (id: string) => ({ id, type: 'new_version', source: 'edit-diff', edited: true, image: { w: 2400, h: 1046 }, page: 2,
  pages: [{ page: 1, n_changes: 0 }, { page: 2, n_changes: 2 }], counts: { removed: 1, added: 0, moved: 1, material: 0 },
  v1: { label: 'Original', page_image: `/api/docs/${doc}/pages/2/image`, thumb: '' },
  v2: { label: 'Edited version 2', page_image: `/api/docs/${doc}/versions/2/pages/2/image`, thumb: '' },
  changes: [
    { n: 1, change_id: 'c1', type: 'removed', kind: 'door', sentence: 'Door D30 (Tür-015) was removed.', edit: true, action: 'removed', item_id: 'DOOR', tag: 'D30',
      v1: { item_id: 'DOOR', bbox_px: [802, 416, 857, 422] }, v2: null },
    { n: 2, change_id: 'c2', type: 'modified', kind: 'window', sentence: 'Window W81 (Fenster-005) moved 1.0 m east.', edit: true, action: 'moved', item_id: 'WIN', tag: 'W81',
      v1: { item_id: 'WIN', bbox_px: [1711, 156, 1766, 161] }, v2: { item_id: 'WIN', bbox_px: [1766, 156, 1821, 161] } },
  ] })
let host: HTMLDivElement
let root: Root
let transport: ReturnType<typeof vi.fn>
const settle = async () => { for (let i = 0; i < 4; i++) await new Promise((resolve) => setTimeout(resolve, 0)) }

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  workspaceApi.isDemo = false
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  transport = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url === '/api/changes') return Response.json({ changes: [entry(0, 1), entry(1, 2)] })
    return Response.json(detail(decodeURIComponent(url.split('/api/changes/')[1].split('?')[0])))
  })
  vi.stubGlobal('fetch', transport)
})
afterEach(async () => {
  await act(async () => root.unmount()); host.remove()
  window.location.hash = ''
  vi.restoreAllMocks(); vi.unstubAllGlobals()
})
function select(label: string, value: string) {
  const input = host.querySelector<HTMLSelectElement>(`[aria-label="${label}"]`)!
  input.value = value; input.dispatchEvent(new Event('change', { bubbles: true }))
}

it('compares any two saved versions of an edited design, with item ids and moved boxes', async () => {
  window.location.hash = `#/compare?change=${encodeURIComponent(`${prefix}1-2`)}`
  await act(async () => { root.render(<CompareScreen docs={[]} demo={false} />); await settle() })
  const from = host.querySelector<HTMLSelectElement>('[aria-label="From version"]')!
  const to = host.querySelector<HTMLSelectElement>('[aria-label="To version"]')!
  expect([from.value, to.value]).toEqual(['1', '2'])
  expect([...from.options].map((o) => o.text)).toEqual(['Original', 'Edited version 1'])
  expect(host.querySelector('[aria-label="Drawing"] option')?.textContent).toBe('AC20 · edited in 3D')
  await act(async () => { select('From version', '0'); await settle() })
  expect(transport.mock.calls.map(([u]) => decodeURIComponent(String(u)))).toContain(`/api/changes/${prefix}0-2`)
  const readings = host.querySelector('[aria-label="Differences"]')!
  expect(readings.textContent).toContain('Door D30 (Tür-015) was removed.')
  expect(readings.textContent).toContain('1 item removed, 1 item moved.')
  expect(readings.textContent).toContain('generated from 3D edits')
  expect([...readings.querySelectorAll('article')].map((a) => a.getAttribute('data-item-id'))).toEqual(['DOOR', 'WIN'])
  expect(host.querySelectorAll('.cmp-box.moved')).toHaveLength(2)  // old and new spot of the window
  expect(host.querySelector<HTMLImageElement>('img[alt="Newer version"]')!.getAttribute('src')).toBe(`/api/docs/${doc}/versions/2/pages/2/image`)
})
