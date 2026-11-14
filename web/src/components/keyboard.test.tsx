// @vitest-environment jsdom
import { act, useState } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ChatHeaderActions } from './chat-header-actions'
import { PairPhoneButton } from './pair-phone'
import { UploadDialog } from './upload-dialog'
import { WorkspaceNavigation } from './workspace-navigation'
import { LibraryScreen } from './library-screen'
import { Tooltip } from './ui/tooltip'
import { DataScreen } from './data-screen'
import { DocumentViewer } from './document-viewer'
import { workspaceApi } from '../lib/api'
import { demoDocument, makeDemoAnswer } from '../mock/handler'

let host: HTMLDivElement
let root: Root
const click = async (node: HTMLElement) => act(async () => { node.focus(); node.click() })
const key = async (value: string, shiftKey = false) => act(async () => {
  document.activeElement!.dispatchEvent(new KeyboardEvent('keydown', { key: value, shiftKey, bubbles: true, cancelable: true }))
})

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  const storage = new Map<string, string>()
  Object.defineProperty(window, 'localStorage', { configurable: true, value: {
    getItem: (name: string) => storage.get(name) ?? null,
    setItem: (name: string, value: string) => storage.set(name, value),
    removeItem: (name: string) => storage.delete(name),
  } })
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addEventListener() {}, removeEventListener() {} })))
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => { callback(0); return 0 })
  window.history.replaceState(null, '', '#/chat')
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ chats: [], skills: [], automations: [] }) })))
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
})

afterEach(async () => {
  await act(async () => root.unmount())
  host.remove()
  vi.restoreAllMocks(); vi.unstubAllGlobals()
})

function checkDialog(selector: string) {
  const panel = document.querySelector<HTMLElement>(selector)!
  expect(panel).not.toBeNull()
  expect(panel.getAttribute('role')).toBe('dialog')
  expect(panel.getAttribute('aria-modal')).toBe('true')
  expect(document.getElementById(panel.getAttribute('aria-labelledby')!)?.textContent?.trim()).toBeTruthy()
  return panel
}

it('History focuses its controls, wraps Tab, closes on Escape and restores its trigger', async () => {
  await act(async () => root.render(<ChatHeaderActions chatId={null} onNew={() => {}} />))
  const trigger = host.querySelector<HTMLButtonElement>('[aria-label="History"]')!
  await click(trigger)
  const panel = checkDialog('#chat-history')
  const controls = panel.querySelectorAll<HTMLElement>('button, input')
  expect(document.activeElement).toBe(controls[0])
  expect(trigger.hasAttribute('inert')).toBe(true)
  await key('Tab', true)
  expect(document.activeElement).toBe(controls[controls.length - 1])
  await key('Tab')
  expect(document.activeElement).toBe(controls[0])
  await key('Escape')
  expect(document.querySelector('#chat-history')).toBeNull()
  expect(document.activeElement).toBe(trigger)
  expect(document.querySelector('[inert]')).toBeNull()
})

it('pairing closes on Escape or its close button and restores the trigger', async () => {
  await act(async () => root.render(<PairPhoneButton />))
  const trigger = host.querySelector<HTMLButtonElement>('[aria-label="Pair a phone"]')!
  await click(trigger)
  const panel = checkDialog('.pair-popover')
  expect(document.activeElement).toBe(panel.querySelector('[aria-label="Close pairing"]'))
  await key('Escape')
  expect(document.querySelector('.pair-popover')).toBeNull()
  expect(document.activeElement).toBe(trigger)
  await click(trigger)
  await click(host.querySelector<HTMLButtonElement>('[aria-label="Close pairing"]')!)
  expect(document.activeElement).toBe(trigger)
  expect(document.querySelector('[inert]')).toBeNull()
})

it('pairing QR encodes the native app link; the https link stays as text under it', async () => {
  const { default: qrcode } = await import('qrcode-generator')
  await act(async () => root.render(<PairPhoneButton />))
  await click(host.querySelector<HTMLButtonElement>('[aria-label="Pair a phone"]')!)
  const link = document.querySelector<HTMLInputElement>('input[aria-label="Pairing link"]')!.value
  const code = new URL(link).hash.match(/code=(\w+)/)![1]
  const expected = qrcode(0, 'M'); expected.addData(`hologram://pair?code=${code}`); expected.make()
  const reference = document.createElement('div'); reference.innerHTML = expected.createSvgTag({ cellSize: 4, margin: 2, scalable: true })
  expect(document.querySelector('.pair-qr')!.innerHTML).toBe(reference.innerHTML)
  expect(link).toMatch(/^https?:\/\/.*#\/pair\?code=/)
  expect(document.querySelector('.pair-popover')!.textContent).toContain('Scan with your iPhone camera to open Stoa Pro')
  expect(document.querySelector('.pair-popover')!.textContent).toContain('No app? Open in browser')
})

it('upload handles the native Escape cancel event and returns focus to Upload', async () => {
  // jsdom has no native dialog behavior: model the browser's Escape -> cancel default action.
  const nativeEscape = (event: KeyboardEvent) => {
    if (event.key === 'Escape') document.querySelector('dialog[open]')?.dispatchEvent(new Event('cancel', { cancelable: true }))
  }
  const originalShow = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, 'showModal')
  const originalClose = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, 'close')
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value: function (this: HTMLDialogElement) {
    this.setAttribute('open', '')
    this.querySelector<HTMLElement>('button')?.focus()
    document.addEventListener('keydown', nativeEscape)
  } })
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value: function (this: HTMLDialogElement) {
    this.removeAttribute('open')
    document.removeEventListener('keydown', nativeEscape)
  } })
  function Harness() {
    const [open, setOpen] = useState(false)
    return <><button onClick={() => setOpen(true)}>Upload</button><UploadDialog open={open} onClose={() => setOpen(false)} onAsk={() => {}} onOpen={() => {}} /></>
  }
  try {
    await act(async () => root.render(<Harness />))
    const trigger = host.querySelector('button')!
    await click(trigger)
    const panel = checkDialog('dialog.upload-dialog')
    expect(panel.contains(document.activeElement)).toBe(true)
    await key('Escape')
    expect(document.querySelector('dialog.upload-dialog')).toBeNull()
    expect(document.activeElement).toBe(trigger)
  } finally {
    await act(async () => root.render(null))
    document.removeEventListener('keydown', nativeEscape)
    if (originalShow) Object.defineProperty(HTMLDialogElement.prototype, 'showModal', originalShow)
    else Reflect.deleteProperty(HTMLDialogElement.prototype, 'showModal')
    if (originalClose) Object.defineProperty(HTMLDialogElement.prototype, 'close', originalClose)
    else Reflect.deleteProperty(HTMLDialogElement.prototype, 'close')
  }
})

it.each(['.help-more', '.mobile-more'])('%s closes with Escape and focuses its summary', async (selector) => {
  await act(async () => root.render(<WorkspaceNavigation route="chat" />))
  const details = host.querySelector<HTMLDetailsElement>(selector)!
  details.open = true
  details.querySelector('a')!.focus()
  await key('Escape')
  expect(details.open).toBe(false)
  expect(document.activeElement).toBe(details.querySelector('summary'))
})

it('Library tabs support arrows, Home and End and label the panel', async () => {
  await act(async () => root.render(<LibraryScreen docs={[]} />))
  const [skills, automations] = host.querySelectorAll<HTMLButtonElement>('[role="tab"]')
  skills.focus()
  await key('ArrowRight')
  expect(document.activeElement).toBe(automations)
  expect(automations.getAttribute('aria-selected')).toBe('true')
  expect(host.querySelector('[role="tabpanel"]')?.getAttribute('aria-labelledby')).toBe(automations.id)
  await key('Home')
  expect(document.activeElement).toBe(skills)
  await key('End')
  expect(document.activeElement).toBe(automations)
})

it('Escape dismisses a tooltip while keeping focus on its control', async () => {
  await act(async () => root.render(<Tooltip content="Details"><button>Open details</button></Tooltip>))
  const trigger = host.querySelector('button')!
  trigger.focus()
  await key('Escape')
  expect(host.querySelector<HTMLElement>('[role="tooltip"]')?.style.display).toBe('none')
  expect(document.activeElement).toBe(trigger)
})

async function openDataDocument(phone = false) {
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: phone, addEventListener() {}, removeEventListener() {} })))
  vi.spyOn(workspaceApi, 'hasScene').mockResolvedValue(false)
  await act(async () => root.render(<DataScreen docs={[demoDocument]} loading={false} demo hidden={false} onRefresh={async () => {}} onAsk={() => {}} />))
  const trigger = host.querySelector<HTMLButtonElement>('.data-open-file')!
  await click(trigger)
  return trigger
}

it.each([false, true])('Data Escape dismisses credit, then page search, then the preview (phone=%s)', async (phone) => {
  const trigger = await openDataDocument(phone)
  const panel = host.querySelector<HTMLElement>('.data-detail')!
  const search = panel.querySelector<HTMLButtonElement>('[aria-label="Search page text"]')!
  await click(search)
  expect(document.activeElement).toBe(panel.querySelector('[aria-label="Find in page text"]'))
  const credit = panel.querySelector<HTMLDetailsElement>('.data-credit-info')!
  const summary = credit.querySelector('summary')!
  await click(summary)
  expect(credit.open).toBe(true)
  await key('Escape')
  expect(credit.open).toBe(false)
  expect(document.activeElement).toBe(summary)
  expect(panel.querySelector('.data-page-search')).not.toBeNull()
  await key('Escape')
  expect(panel.querySelector('.data-page-search')).toBeNull()
  expect(document.activeElement).toBe(search)
  expect(panel.isConnected).toBe(true)
  await key('Escape')
  expect(panel.isConnected).toBe(false)
  expect(document.activeElement).toBe(trigger)
})

it('Data page-search close button restores its Search trigger', async () => {
  await openDataDocument()
  const search = host.querySelector<HTMLButtonElement>('[aria-label="Search page text"]')!
  await click(search)
  await click(host.querySelector<HTMLButtonElement>('[aria-label="Close page search"]')!)
  expect(host.querySelector('.data-page-search')).toBeNull()
  expect(document.activeElement).toBe(search)
  expect(host.querySelector('.data-detail')).not.toBeNull()
})

it.each(['Escape', 'button'])('mobile Data detail has a visible dialog title, contains Tab, and returns focus on %s close', async (method) => {
  const trigger = await openDataDocument(true)
  const panel = checkDialog('.data-detail')
  expect(document.getElementById(panel.getAttribute('aria-labelledby')!)?.textContent).toBe(demoDocument.title)
  expect(panel.contains(document.activeElement)).toBe(true)
  expect(trigger.closest('[inert]')).not.toBeNull()
  const first = panel.querySelector('summary')!
  const last = panel.querySelector<HTMLButtonElement>('.data-detail-actions button')!
  first.focus()
  await key('Tab', true)
  expect(document.activeElement).toBe(last)
  await key('Tab')
  expect(document.activeElement).toBe(first)
  if (method === 'Escape') await key('Escape')
  else await click(panel.querySelector<HTMLButtonElement>('[aria-label="Close document details"]')!)
  expect(host.querySelector('.data-detail')).toBeNull()
  expect(document.activeElement).toBe(trigger)
  expect(document.querySelector('[inert]')).toBeNull()
})

it.each([false, true])('viewer search restores Search on Escape and button close, and sheets use their visible title (sheet=%s)', async (sheet) => {
  vi.spyOn(workspaceApi, 'getDocument').mockResolvedValue(demoDocument)
  vi.spyOn(workspaceApi, 'getPageImage').mockResolvedValue(new Blob())
  vi.spyOn(workspaceApi, 'getDocumentTags').mockResolvedValue({})
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:demo') })
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
  const onClose = vi.fn()
  const answer = makeDemoAnswer('How many windows?')
  await act(async () => root.render(<DocumentViewer answer={answer} citation={answer.citations[0]} sheet={sheet} onClose={onClose} />))
  if (sheet) {
    const panel = checkDialog('.document-viewer')
    const title = document.getElementById(panel.getAttribute('aria-labelledby')!)!
    expect(title).toBe(panel.querySelector('.viewer-heading strong'))
    expect(title.textContent).toBe(demoDocument.title)
  }
  const search = host.querySelector<HTMLButtonElement>('[aria-label="Search sheet"]')!
  for (const method of ['Escape', 'button']) {
    await click(search)
    expect(document.activeElement).toBe(host.querySelector('[aria-label="Find on sheet"]'))
    if (method === 'Escape') await key('Escape')
    else await click(host.querySelector<HTMLButtonElement>('[aria-label="Close sheet search"]')!)
    expect(host.querySelector('#viewer-sheet-search')).toBeNull()
    expect(document.activeElement).toBe(search)
    expect(onClose).not.toHaveBeenCalled()
  }
  await key('Escape')
  expect(onClose).toHaveBeenCalledOnce()
})
