// @vitest-environment jsdom
import { act, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DataScreen, type FileDocument } from './data-screen'
import { ChangesScreen } from './changes-screen'
import { LibraryScreen } from './library-screen'
import { CompareScreen } from './compare-screen'
import App from '../App'
import { useRoute } from '../lib/router'
import { workspaceApi } from '../lib/api'
import type { Comparison } from '../lib/types'

// Generated fixtures for interaction tests; no project drawing data.
const drawing: FileDocument = {
  doc_id: 'test__drawing', title: 'Drawing generated for demo', source: 'test', folder: 'Plans',
  formats: ['pdf'], kind: 'pdf', pages: 1, licence: 'MIT', credit: 'generated for demo', heldout: false,
}
const comparison: Comparison = {
  id: 'test-comparison', type: 'new_version', doc_a: 'test__older', doc_b: drawing.doc_id,
  doc_id: drawing.doc_id, created_at: '2026-11-14T10:00:00Z', summary: { title: drawing.title },
  generated_for_demo: true, source: 'test', image: { w: 100, h: 100 },
  v1: { label: 'Version 1', page_image: '/older.png', thumb: '/older-thumb.png' },
  v2: { label: 'Version 2', page_image: '/newer.png', thumb: '/newer-thumb.png' }, changes: [],
}
const refresh = vi.fn(async () => {})
const ask = vi.fn()
const showModal = vi.fn(function (this: HTMLDialogElement) { this.open = true })
let host: HTMLDivElement
let root: Root

function UploadHarness({ children, docs = [] }: { children: ReactNode; docs?: FileDocument[] }) {
  const route = useRoute()
  return <>
    <DataScreen docs={docs} loading={false} demo={false} hidden={route !== 'data'} onRefresh={refresh} onAsk={ask} />
    {route !== 'data' && children}
  </>
}

async function render(content: ReactNode) { await act(async () => { root.render(content) }) }
async function click(element: HTMLElement) {
  await act(async () => { element.click(); await new Promise((resolve) => setTimeout(resolve, 0)) })
}
function button(text: string, within: ParentNode = host) {
  const found = [...within.querySelectorAll<HTMLButtonElement>('button')].find((node) => node.textContent === text)
  expect(found, `Button: ${text}`).toBeTruthy()
  return found!
}
async function change(element: HTMLInputElement | HTMLSelectElement, value: string) {
  await act(async () => {
    if (element instanceof HTMLInputElement) {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(element, value)
      element.dispatchEvent(new Event('input', { bubbles: true }))
    } else {
      element.value = value
      element.dispatchEvent(new Event('change', { bubbles: true }))
    }
  })
}

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  window.history.replaceState(null, '', '#/data')
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ folders: [], skills: [], automations: [] }) })))
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addEventListener() {}, removeEventListener() {} })))
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value: showModal })
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value() { this.open = false } })
  vi.spyOn(workspaceApi, 'getChanges').mockResolvedValue([])
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
})

afterEach(async () => {
  await act(async () => { root.unmount(); await new Promise((resolve) => setTimeout(resolve, 0)) })
  host.remove()
  vi.restoreAllMocks()
  vi.clearAllMocks()
  vi.unstubAllGlobals()
})

describe('empty-state next steps', () => {
  it('clears a Data search and restores documents across folders', async () => {
    await render(<DataScreen docs={[drawing]} loading={false} demo={false} hidden={false} onRefresh={refresh} onAsk={ask} />)
    const search = host.querySelector<HTMLInputElement>('[aria-label="Search documents"]')!
    await change(search, 'no matching drawing')
    expect(host.textContent).toContain('No documents match')
    await click(button('Clear search'))
    expect(search.value).toBe('')
    expect(host.querySelector(`[data-doc-id="${drawing.doc_id}"]`)).not.toBeNull()
  })

  it('opens the existing upload dialog from Data search results', async () => {
    await render(<DataScreen docs={[drawing]} loading={false} demo={false} hidden={false} onRefresh={refresh} onAsk={ask} />)
    await change(host.querySelector<HTMLInputElement>('[aria-label="Search documents"]')!, 'no match')
    await click(button('Upload', host.querySelector('.data-empty')!))
    expect(showModal).toHaveBeenCalledOnce()
    expect(document.querySelector('dialog[open]')?.textContent).toContain('Upload a drawing')
  })

  it('opens upload when Data has no documents', async () => {
    await render(<DataScreen docs={[]} loading={false} demo={false} hidden={false} onRefresh={refresh} onAsk={ask} />)
    await click(button('Upload', host.querySelector('.data-empty')!))
    expect(showModal).toHaveBeenCalledOnce()
  })

  it('opens the Data upload session from an empty Changes feed', async () => {
    window.history.replaceState(null, '', '#/changes')
    await render(<UploadHarness><ChangesScreen docs={[]} demo={false} /></UploadHarness>)
    await click(button('Upload', host.querySelector('.changes-no-data')!))
    expect(showModal).toHaveBeenCalledOnce()
    expect(window.location.hash).toBe('#/data')
  })

  it.each(['Change type', 'Change folder'])('clears a %s filter without a search query', async (label) => {
    vi.mocked(workspaceApi.getChanges).mockResolvedValue([{ ...comparison, type: 'new_document' }])
    await render(<ChangesScreen docs={[drawing]} demo={false} />)
    const filter = host.querySelector<HTMLSelectElement>(`[aria-label="${label}"]`)!
    await change(filter, label === 'Change type' ? 'new_version' : 'Plans')
    const clear = host.querySelector<HTMLButtonElement>('[aria-label="Clear change filters"]')!
    expect(clear.disabled).toBe(false)
    await click(clear)
    expect(filter.value).toBe('')
    expect(clear.disabled).toBe(true)
    expect(host.querySelector(`[data-change-id="${comparison.id}"]`)).not.toBeNull()
  })

  it.skip('opens upload from Library Automations without documents', async () => {
    window.history.replaceState(null, '', '#/library')
    await render(<UploadHarness><LibraryScreen docs={[]} /></UploadHarness>)
    await click(button('Automations'))
    expect(host.textContent).toContain('Upload a drawing to create an automation.')
    await click(button('Upload', host.querySelector('.library-empty')!))
    expect(showModal).toHaveBeenCalledOnce()
  })

  it('opens upload from Compare without versions', async () => {
    window.history.replaceState(null, '', '#/compare')
    await render(<UploadHarness><CompareScreen docs={[]} demo={false} /></UploadHarness>)
    await click(button('Upload a new version'))
    expect(showModal).toHaveBeenCalledOnce()
  })

  it('opens chat with the drawing after a comparison finds no differences', async () => {
    window.history.replaceState(null, '', '#/compare')
    vi.mocked(workspaceApi.getChanges).mockResolvedValue([comparison])
    // Live comparison payloads identify the drawing in the feed, without doc_id on the comparison.
    const { doc_id: _docId, ...liveComparison } = comparison
    vi.spyOn(workspaceApi, 'getComparison').mockResolvedValue(liveComparison as Comparison)
    vi.spyOn(workspaceApi, 'getDocuments').mockResolvedValue([drawing])
    await render(<App />)
    expect(host.querySelector('.selected-documents')).toBeNull()
    await act(async () => {
      const navigated = new Promise<void>((resolve) => window.addEventListener('hashchange', () => resolve(), { once: true }))
      host.querySelector<HTMLAnchorElement>('.cmp-empty a')!.click()
      await navigated
    })
    expect(window.location.hash).toBe(`#/chat?doc=${drawing.doc_id}`)
    expect(host.querySelector('.route-chat')).not.toBeNull()
    expect(host.querySelector('.chat-workspace')?.hasAttribute('hidden')).toBe(false)
    expect(host.querySelector('.selected-documents')?.textContent).toContain(drawing.title)
  })
})


describe('document metadata', () => {
  it('omits missing size, date, and version fields and preserves recorded zeroes', async () => {
    await render(<DataScreen docs={[drawing]} loading={false} demo={true} hidden={false} onRefresh={refresh} onAsk={ask} />)
    expect(host.querySelector('[aria-label="File size"]')).toBeNull()
    expect(host.querySelector('[aria-label="File date"]')).toBeNull()
    expect(host.textContent).not.toMatch(/size unavailable|version count unavailable|date unavailable/i)
    expect(host.querySelector('.data-file-facts')?.textContent).toBe('')
    await render(<DataScreen docs={[{ ...drawing, size: 0, version_count: 1, date: '2026-11-14' }]} loading={false} demo={true} hidden={false} onRefresh={refresh} onAsk={ask} />)
    expect(host.querySelector('[aria-label="File size"]')?.textContent).toBe('0 B')
    expect(host.querySelector('[aria-label="File date"]')?.textContent).toContain('2026')
    expect(host.querySelector('.data-file-facts')?.textContent).toContain('1 version')
  })
})
