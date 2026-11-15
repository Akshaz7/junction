// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { SheetOverlay } from './sheet-overlay'
import { requestAlignment } from '../lib/sheet-overlay'

vi.mock('../lib/api', () => ({ workspaceApi: { getDocuments: vi.fn(async () => [
  { doc_id: 'base', title: 'Floor plan 3rd floor', pages: 1, kind: 'pdf' },
  { doc_id: 'other', title: 'Ventilation 3RD FLOOR', pages: 1, kind: 'pdf' },
]), getPageImage: vi.fn(async () => new Blob(['page'])) } }))
vi.mock('../lib/sheet-overlay', async (original) => ({ ...await original<typeof import('../lib/sheet-overlay')>(), requestAlignment: vi.fn(), registeredSheet: vi.fn(async () => 'blob:registered') }))
let host: HTMLDivElement, root: Root
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:source'), revokeObjectURL: vi.fn() }))
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
})
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.clearAllMocks() })

it('opens a sheet picker and never presents identity registration as automatic alignment', async () => {
  await act(async () => root.render(<SheetOverlay baseDocId="base" onClose={() => {}} />))
  expect(host.textContent).toContain('Choose another discipline')
  expect(host.querySelector('select')?.textContent).toContain('Ventilation')
  expect(requestAlignment).not.toHaveBeenCalled()
})

it('explains insufficient anchors and offers manual picking before showing an overlay', async () => {
  vi.mocked(requestAlignment).mockResolvedValueOnce({ status: 'needs_manual', matrix: null, method: null, anchor_count: 0, candidate_count: 1, residual_px: null, residual_mm: null, detail: 'Too few shared labels. Use two grid crossings.', anchors: [], base_image: {w: 1000,h: 800}, overlay_image: {w: 1200,h: 900} })
  await act(async () => root.render(<SheetOverlay baseDocId="base" initialOverlayDocId="other" onClose={() => {}} />))
  expect(host.textContent).toContain('Too few shared labels')
  expect(host.querySelector('.overlay-compare')).toBeNull()
  const button = [...host.querySelectorAll('button')].find((b) => b.textContent === 'Align with two points')!
  await act(async () => button.click())
  expect(host.textContent).toContain('same two grid crossings')
  const apply = [...host.querySelectorAll('button')].find((b) => b.textContent === 'Apply alignment')!
  expect(apply.disabled).toBe(true)
})

it('a failed alignment request has an actionable retry and no drawing overlay', async () => {
  vi.mocked(requestAlignment).mockRejectedValueOnce(new Error('Page image is missing'))
  await act(async () => root.render(<SheetOverlay baseDocId="base" initialOverlayDocId="other" onClose={() => {}} />))
  expect(host.querySelector('[role=alert]')?.textContent).toContain('Page image is missing')
  expect(host.querySelector('.overlay-compare')).toBeNull()
})

it('uses the shared compare modes, opacity and layer controls after registration', async () => {
  vi.mocked(requestAlignment).mockResolvedValueOnce({ status: 'aligned', matrix: [[1, 0, 5], [0, 1, 10]], method: 'similarity', anchor_count: 4, candidate_count: 5, residual_px: .5, residual_mm: null, detail: 'Aligned on 4 shared labels, ± 0.5 px', anchors: [], base_image: { w: 1000, h: 800 }, overlay_image: { w: 1200, h: 900 } })
  await act(async () => root.render(<SheetOverlay baseDocId="base" initialOverlayDocId="other" onClose={() => {}} />))
  expect(host.querySelectorAll('.sheet-compare')).toHaveLength(1)
  expect(host.querySelector('.sheet-compare')?.getAttribute('data-mode')).toBe('Overlay')
  expect(host.querySelector('[aria-label="Overlay opacity"]')).not.toBeNull()
  const checkbox = host.querySelector<HTMLInputElement>('.overlay-controls input')!
  await act(async () => checkbox.click())
  expect(host.querySelector('.overlay-compare')?.getAttribute('data-base-visible')).toBe('false')
  const wipe = [...host.querySelectorAll('button')].find((button) => button.textContent === 'Wipe')!
  await act(async () => wipe.click())
  expect(host.querySelector('.sheet-compare')?.getAttribute('data-mode')).toBe('Wipe')
  expect(host.querySelector('[aria-label="Wipe position"]')).not.toBeNull()
})
