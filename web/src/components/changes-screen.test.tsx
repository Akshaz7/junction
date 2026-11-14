// @vitest-environment jsdom
// API fixtures generated for demo tests; ids and shape follow real issued sheets.
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ChangesScreen } from './changes-screen'
import { CompareScreen } from './compare-screen'
import { workspaceApi } from '../lib/api'

const older = 'opening_design__sports-complex-transfer-archive-20150811-restroom-markups-locker-rooms-and-restrooms'
const newer = 'opening_design__sports-complex-transfer-archive-20150812-restroom-markups-locker-rooms-and-restrooms'
const id = 'ser:sports-restrooms:1'
const entry = { id, type: 'new_version', doc_a: older, doc_b: newer, created_at: '2015-08-12T00:00:00+00:00', summary: {
  doc_id: newer, title: 'Locker Rooms and Restrooms', series_id: 'sports-restrooms', discipline: 'Architecture', n_changes: null,
  version_a: 'Version 1 · 2015-08-11', version_b: 'Version 2 · 2015-08-12',
  headline: 'New issue of Locker Rooms and Restrooms (7 → 6 pages). Comparison not available.',
} }
const detail = { id, source: 'pdf-diff', status: 'not_built', image: null, changes: [], note: entry.summary.headline,
  v1: { doc_id: older, label: entry.summary.version_a, pages: 7 }, v2: { doc_id: newer, label: entry.summary.version_b, pages: 6 } }
let host: HTMLDivElement
let root: Root
let transport: ReturnType<typeof vi.fn>
const settle = async () => { await new Promise((resolve) => setTimeout(resolve, 0)) }

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  workspaceApi.isDemo = false
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  transport = vi.fn(async (input: RequestInfo | URL) => String(input) === '/api/changes'
    ? Response.json({ changes: [entry, { ...entry, id: 'ser:structure:1', summary: { ...entry.summary, title: 'Foundation Plans', discipline: 'Structural' } },
      { id: 'doc:uploads__new', type: 'new_document', doc_a: null, doc_b: 'uploads__new', created_at: '2026-11-14T10:00:00Z', summary: { title: 'Uploaded drawing' } }] })
    : Response.json(detail))
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

it('renders real issue facts, combines discipline/type filters, and opens the exact docs in Compare', async () => {
  await act(async () => { root.render(<ChangesScreen docs={[]} demo={false} />); await settle() })
  expect(host.querySelectorAll('.change-row')).toHaveLength(3)
  await act(async () => { select('Change discipline', 'Architecture'); select('Change type', 'new_version') })
  const rows = host.querySelectorAll<HTMLButtonElement>('.change-row')
  expect(rows).toHaveLength(1)
  expect(rows[0].textContent).toContain('7 → 6 pages')
  expect(rows[0].textContent).toContain('Architecture')
  expect(host.textContent).not.toContain('null changes')
  await act(async () => { rows[0].click(); await settle() })
  expect(transport).toHaveBeenCalledWith(`/api/changes/${encodeURIComponent(id)}`, expect.objectContaining({ signal: expect.any(AbortSignal) }))
  expect(host.querySelector('[aria-label="Revision details"]')?.textContent).toContain('Comparison not available')
  expect([...host.querySelectorAll<HTMLAnchorElement>('.revision-documents a')].map((a) => a.getAttribute('href'))).toEqual([
    `#/data?doc=${encodeURIComponent(older)}`, `#/data?doc=${encodeURIComponent(newer)}`,
  ])
  const compare = host.querySelector<HTMLAnchorElement>('.open-compare')!
  expect(compare.hash).toBe(`#/compare?change=${encodeURIComponent(id)}`)
  window.location.hash = compare.hash
  await act(async () => { root.render(<CompareScreen docs={[]} demo={false} />); await settle() })
  expect(host.querySelector<HTMLSelectElement>('[aria-label="Versions"]')?.value).toBe(id)
  expect(host.textContent).not.toContain('Version Version')
  expect(host.textContent).not.toContain('No differences were found')
  expect(host.querySelector('[aria-label="Revision details"]')?.textContent).toContain('7 pages')
})

it('shows the two real page images when a comparison exists and clears filters', async () => {
  transport.mockImplementation(async (input: RequestInfo | URL) => String(input) === '/api/changes' ? Response.json({ changes: [entry] }) : Response.json({
    ...detail, status: undefined, image: { w: 100, h: 80 },
    v1: { ...detail.v1, page_image: `/api/docs/${older}/pages/1/image` },
    v2: { ...detail.v2, page_image: `/api/docs/${newer}/pages/1/image` },
  }))
  await act(async () => { root.render(<ChangesScreen docs={[]} demo={false} />); await settle() })
  await act(async () => { host.querySelector<HTMLButtonElement>('.change-row')!.click(); await settle() })
  expect(host.querySelector<HTMLImageElement>('[alt="Previous revision"]')?.getAttribute('src')).toBe(`/api/docs/${older}/pages/1/image`)
  expect(host.querySelector<HTMLImageElement>('[alt="Latest revision"]')?.getAttribute('src')).toBe(`/api/docs/${newer}/pages/1/image`)
  await act(async () => { select('Change type', 'new_document') })
  expect(host.textContent).toContain('No changes match these filters')
  await act(async () => host.querySelector<HTMLButtonElement>('[aria-label="Clear change filters"]')!.click())
  expect(host.querySelectorAll('.change-row')).toHaveLength(1)
})
