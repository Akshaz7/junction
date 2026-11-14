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
