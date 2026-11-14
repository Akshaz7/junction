// @vitest-environment jsdom
import { act, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { DataScreen } from './data-screen'
import { ProjectSwitcher, WorkspaceNavigation } from './workspace-navigation'
import { workspaceApi } from '../lib/api'
import type { Document } from '../lib/types'

// Generated fixtures for controls; no project drawing data.
const doc: Document = { doc_id: 'test__controls', source: 'test', title: 'Controls generated for demo', kind: 'pdf', formats: ['pdf'], pages: 2, licence: 'MIT', credit: 'generated for demo', heldout: false }
let host: HTMLDivElement
let root: Root
const ask = vi.fn()
const render = async (children: ReactNode) => { await act(async () => root.render(children)) }
const click = async (element: HTMLElement) => { await act(async () => { element.click() }) }
function control(label: string) {
  const element = host.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`)
  expect(element, label).not.toBeNull()
  return element!
}
async function query(value: string) {
  await act(async () => {
    const input = host.querySelector<HTMLInputElement>('[aria-label="Find in page text"]')!
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
async function openDocument() {
  await render(<DataScreen docs={[doc]} loading={false} demo={true} hidden={false} onRefresh={async () => {}} onAsk={ask} />)
  await click(control(`Open ${doc.title}`))
}

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addEventListener() {}, removeEventListener() {} })))
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  vi.spyOn(workspaceApi, 'hasScene').mockResolvedValue(false)
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({ ok: true, json: async () => url.includes('/files/text-')
    ? { words: [{ text: url.includes('text-2') ? 'Roof' : 'Kitchen', bbox_px: [1, 2, 30, 40] }] }
    : { items: [] } })))
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
})
afterEach(async () => {
  await act(async () => root.unmount())
  host.remove(); vi.restoreAllMocks(); vi.clearAllMocks(); vi.unstubAllGlobals()
})

it('searches actual page text, refreshes it on page navigation, and closes search', async () => {
  await openDocument()
  await click(control('Search page text'))
  expect(control('Search page text').getAttribute('aria-expanded')).toBe('true')
  await query('kitchen')
  expect(host.querySelector('.data-page-search')?.textContent).toContain('1 matches on page 1')
  expect(host.querySelector('.data-page-search li')?.textContent).toBe('Kitchen')
  await click(control('Next drawing page'))
  expect(host.querySelector('.data-page-search li')).toBeNull()
  await query('roof')
  expect(host.querySelector('.data-page-search li')?.textContent).toBe('Roof')
  expect(fetch).toHaveBeenCalledWith('/api/docs/test__controls/files/text-2.json', expect.anything())
  await click(control('Close page search'))
  expect(host.querySelector('.data-page-search')).toBeNull()
  expect(control('Search page text').getAttribute('aria-expanded')).toBe('false')
  await click(control('Search page text'))
  await click(control('Search page text'))
  expect(host.querySelector('.data-page-search')).toBeNull()
})

it('shows an honest empty state for a page without extracted text', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 404 })))
  await openDocument()
  await click(control('Search page text'))
  expect(host.querySelector('.data-page-search')?.textContent).toContain('No searchable text is available on this page.')
})

it('changes the preview and download together and disables page boundaries', async () => {
  await openDocument()
  expect(control('Previous drawing page').disabled).toBe(true)
  await click(control('Next drawing page'))
  expect(control('Next drawing page').disabled).toBe(true)
  expect(host.querySelector('.data-preview img')?.getAttribute('src')).toBe('/api/docs/test__controls/pages/2/image')
  const download = host.querySelector<HTMLAnchorElement>('[aria-label="Download page"]')!
  let clicked = false
  download.addEventListener('click', (event) => { event.preventDefault(); clicked = true })
  await click(download)
  expect(clicked).toBe(true)
  expect(download.getAttribute('href')).toBe('/api/docs/test__controls/pages/2/image')
  expect(download.hasAttribute('download')).toBe(true)
  await click(control('Previous drawing page'))
  expect(host.querySelector('.data-preview img')?.getAttribute('src')).toBe('/api/docs/test__controls/pages/1/image')
})

it('keeps functional zoom, fit, ask, credit, revisions and close controls', async () => {
  await openDocument()
  await click(control('Zoom in'))
  expect(host.querySelector('[aria-label="Page zoom level"]')?.textContent).toBe('125%')
  await click(control('Zoom out'))
  expect(host.querySelector('[aria-label="Page zoom level"]')?.textContent).toBe('100%')
  await click(control('Zoom out'))
  await click(control('Fit page'))
  expect(host.querySelector('[aria-label="Page zoom level"]')?.textContent).toBe('100%')
  await click(control('Ask about it'))
  await click(host.querySelector<HTMLButtonElement>('.data-detail-actions button')!)
  expect(ask).toHaveBeenCalledTimes(2)
  expect(ask).toHaveBeenLastCalledWith(doc)
  const credit = host.querySelector<HTMLElement>('summary[aria-label="Drawing credit and licence"]')!
  await click(credit)
  expect(credit.parentElement?.hasAttribute('open')).toBe(true)
  expect(credit.parentElement?.textContent).toContain('MIT')
  const revisions = host.querySelector<HTMLAnchorElement>('.data-compare')!
  revisions.addEventListener('click', (event) => event.preventDefault())
  await click(revisions)
  expect(revisions.getAttribute('href')).toBe('#/changes')
  await click(control('Close document details'))
  expect(host.querySelector('.data-detail')).toBeNull()
})

it('removes decorative controls and leaves project and avatar as static labels', async () => {
  await render(<><ProjectSwitcher /><WorkspaceNavigation route="data" /></>)
  expect(host.querySelector('.project-switcher select')).toBeNull()
  expect(host.querySelector('.project-switcher')?.textContent).toContain('Construction project')
  const avatar = host.querySelector('.workspace-avatar')!
  expect(avatar.textContent).toBe('AK')
  expect(avatar.closest('a, button, summary, [role="button"]')).toBeNull()
  await openDocument()
  expect(host.querySelector('.file-checkbox, .file-row-more, .mobile-folder-back, .mobile-folder-filter, .data-viewer-tools')).toBeNull()
  expect(host.querySelector('.lucide-folder-plus')).toBeNull()
  expect(host.textContent).not.toContain('Visualise it')
})
