// @vitest-environment jsdom
// Generated for demo fixtures, independent of the real document registry.
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { VersionPairCompare, revisionTitle, suggestVersions, type PairComparison } from './changes-screen.pair'
import type { FileDocument } from './data-screen'

vi.mock('../viewer3d/Viewer3D', () => ({ Viewer3D: ({ doc_id }: { doc_id: string }) => <div data-testid="revision-model">{doc_id}</div> }))
const doc = (id: string, title: string, kind: FileDocument['kind'] = 'dxf'): FileDocument => ({ doc_id: id, title, kind, source: 'test', formats: [kind], pages: 1, licence: 'MIT', credit: '', heldout: false })
const docs = [doc('old', 'Office rev A'), doc('new', 'Office rev B'), doc('third', 'Unrelated')]
const zero = { total: 0, added: 0, removed: 0, moved: 0, resized: 0, property_changed: 0 }
const fixture = (): PairComparison => ({ doc_a: 'old', doc_b: 'new', status: 'ready', method: 'planmap-aligned', note: 'Matched item boxes after alignment.', warnings: [],
  inventory_a: 4, inventory_b: 5, matched_items: 4, versions: [{ doc_id: 'old', label: 'Office rev A' }, { doc_id: 'new', label: 'Office rev B' }],
  summary: { ...zero, total: 1, added: 1, affected_items: 1, by_kind: { window: { ...zero, total: 1, added: 1 } }, by_storey: { 'Level 1': { ...zero, total: 1, added: 1 } } },
  changes: [{ change_id: 'c1', n: 1, type: 'added', kind: 'window', description: 'A window was added.', storey: 'Level 1', page: 1, v1: null,
    v2: { doc_id: 'new', item_id: 'w-new', page: 1, bbox_px: [20, 40, 40, 60], bbox_m: null, storey: 'Level 1' } }],
  pages: [{ page: 1, image_a: { w: 100, h: 80 }, image_b: { w: 200, h: 160 }, page_image_a: '/old.png', page_image_b: '/new.png' }] })
let host: HTMLDivElement, root: Root
let transport: ReturnType<typeof vi.fn>
const settle = async () => { await new Promise((resolve) => setTimeout(resolve, 0)) }
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  transport = vi.fn(async () => Response.json(fixture())); vi.stubGlobal('fetch', transport)
})
afterEach(async () => { await act(async () => root.unmount()); host.remove(); window.location.hash = ''; vi.restoreAllMocks(); vi.unstubAllGlobals() })
async function render() { await act(async () => { root.render(<VersionPairCompare docs={docs} onOpen={vi.fn()} />); await settle() }) }
async function submit() { await act(async () => { host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); await settle() }) }
function select(label: string, value: string) { const el = host.querySelector<HTMLSelectElement>(`[aria-label="${label}"]`)!; el.value = value; el.dispatchEvent(new Event('change', { bubbles: true })) }

it('suggests revisions without relying on any document-specific words', () => {
  expect(revisionTitle('Großer Plan_2026-01-20_Rev-B.ifc')).toBe('großer plan')
  expect(revisionTitle('Office v2')).toBe('office')
  expect(suggestVersions(docs)).toEqual(['old', 'new'])
  expect(suggestVersions([docs[0], docs[2]])).toEqual(['', ''])
})

it('lets users compare any documents, sends both IDs, and renders distinct source dimensions', async () => {
  await render(); expect(host.querySelector<HTMLSelectElement>('[aria-label="Version A"]')?.value).toBe('old')
  await submit()
  expect(transport).toHaveBeenCalledWith('/api/changes/compare', expect.objectContaining({ method: 'POST', body: JSON.stringify({ doc_a: 'old', doc_b: 'new' }) }))
  expect(host.textContent).toContain('1 change across 1 item')
  expect([...host.querySelectorAll('figure img')].map((img) => img.getAttribute('src'))).toEqual(['/old.png', '/new.png'])
  const box = host.querySelector<HTMLElement>('[aria-label="Change 1 in version B"]')!
  expect(box.style.left).toBe('10%'); expect(box.style.top).toBe('25%')
  expect(host.querySelector('[aria-label="How we know"]')?.textContent).toContain('Checked:')
  expect(host.querySelector('.revision-source-links')?.textContent).toContain('Version A · Item absent')
  await act(async () => select('Version B', 'third'))
  expect(host.querySelector('.revision-pair-result')).toBeNull()
})

it('opens comparison links from chat and keeps both source versions', async () => {
  window.location.hash = '#/changes?a=old&b=new'
  await render()
  expect(transport).toHaveBeenCalledTimes(1)
  expect([...host.querySelectorAll<HTMLAnchorElement>('.revision-source-links a')].map((el) => el.hash)).toEqual(['#/data?doc=old', '#/data?doc=new'])
})

it('does not turn unavailable data into zero differences', async () => {
  transport.mockImplementation(async () => Response.json({ ...fixture(), status: 'unavailable', summary: null, changes: [], pages: [], warnings: ['Both versions need drawing data.'] }))
  await render(); await submit()
  expect(host.textContent).toContain('Comparison unavailable')
  expect(host.textContent).toContain('Both versions need drawing data.')
  expect(host.textContent).not.toContain('No differences found')
  expect(host.querySelector('.revision-tiles')).toBeNull()
})

it('labels generated versions clearly', async () => {
  transport.mockImplementation(async () => Response.json({ ...fixture(), generated_for_demo: true }))
  await render(); await submit()
  expect(host.textContent).toContain('Includes content generated for demo.')
})

it('shows API errors and disables selecting the same version twice', async () => {
  transport.mockImplementation(async () => Response.json({ detail: 'Version not available.' }, { status: 404 }))
  await render(); await submit()
  expect(host.querySelector('[role="alert"]')?.textContent).toBe('Version not available.')
  await act(async () => select('Version B', 'old'))
  expect(host.querySelector<HTMLButtonElement>('[type="submit"]')?.disabled).toBe(true)
})

it('ignores an aborted comparison when the user switches versions', async () => {
  let finish: (value: Response) => void = () => {}
  transport.mockImplementation(() => new Promise<Response>((resolve) => { finish = resolve }))
  await render(); await submit()
  await act(async () => select('Version B', 'third'))
  await act(async () => { finish(Response.json(fixture())); await settle() })
  expect(host.querySelector('.revision-pair-result')).toBeNull()
})

it('uses only one IFC viewer and can switch to the version containing a removed item', async () => {
  const data = fixture(); data.method = 'ifc-globalid'; data.pages = []; data.changes[0].type = 'removed'
  data.changes[0].v1 = data.changes[0].v2; data.changes[0].v2 = null
  transport.mockImplementation(async () => Response.json(data))
  await render(); await submit(); await act(settle)
  expect(host.querySelectorAll('[data-testid="revision-model"]')).toHaveLength(1)
  expect(host.querySelector('[data-testid="revision-model"]')?.textContent).toBe('old')
  await act(async () => host.querySelector<HTMLButtonElement>('[aria-label="Model version"] button:last-child')!.click())
  expect(host.querySelector('[data-testid="revision-model"]')?.textContent).toBe('new')
  expect(host.textContent).toContain('This item is absent in this version.')
})
