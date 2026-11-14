// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { demoDocument } from '../mock/handler'

const api = vi.hoisted(() => ({ createChat: vi.fn(), askQuestion: vi.fn(), getChat: vi.fn() }))
vi.mock('../lib/api', async (original) => ({ ...(await original<typeof import('../lib/api')>()), workspaceApi: { ...api, isDemo: false } }))
const live = vi.hoisted(() => ({ listeners: new Set<(event: unknown) => void>() }))
vi.mock('../lib/chat-live', () => ({ chatLive: { subscribe: (fn: (event: unknown) => void) => { live.listeners.add(fn); return () => live.listeners.delete(fn) } } }))
import { ChatScreen } from './chat-screen'
import { rememberChat } from '../lib/known-chats'
import { setFollow } from '../lib/chat-follow'

function fakeStorage() {
  const data = new Map<string, string>()
  Object.defineProperty(window, 'localStorage', { configurable: true, value: {
    getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => { data.set(k, String(v)) },
    removeItem: (k: string) => { data.delete(k) }, clear: () => data.clear() } })
}

let host: HTMLDivElement
let root: Root

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  window.history.replaceState(null, '', '#/chat')
  vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }))
  fakeStorage(); live.listeners.clear()
  api.createChat.mockReset().mockResolvedValue('chat-1')
  api.askQuestion.mockReset()
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
})
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals() })

async function mount() {
  await act(async () => root.render(<ChatScreen docs={[demoDocument]} loadingDocs={false} demo={false} contextDocument={null} hidden={false} onChatChange={() => {}} onOpenCitation={() => {}} />))
}
async function send(text: string) {
  const box = host.querySelector<HTMLTextAreaElement>('#question')!
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(box, text)
    box.dispatchEvent(new Event('input', { bubbles: true }))
  })
  await act(async () => { host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })) })
}

it('a stream that ends with no answer keeps the question, shows an error and Retry', async () => {
  api.askQuestion.mockRejectedValueOnce(new Error('The response ended before an answer arrived. Please try again.'))
  await mount()
  await send('Draft a construction claim')
  const failed = host.querySelector('[data-testid="failed-exchange"]')!
  expect(failed.textContent).toContain('Draft a construction claim')
  expect(failed.querySelector('[role="alert"]')!.textContent).toContain('before an answer arrived')
  expect(host.textContent).not.toContain('No answer yet')
  api.askQuestion.mockRejectedValueOnce(new Error('again'))
  await act(async () => failed.querySelector<HTMLButtonElement>('.retry-button')!.click())
  expect(api.askQuestion).toHaveBeenCalledTimes(2)
  expect(api.askQuestion.mock.calls[1][1]).toBe('Draft a construction claim')
})

it('shows the steps of a long task as they arrive', async () => {
  let finish: (value: never) => void = () => {}
  api.askQuestion.mockImplementation((_c, _q, _d, callbacks) => {
    callbacks.onStatus('Gathering evidence for: claim draft'); callbacks.onStatus('Writing the claim draft…')
    return new Promise((resolve, reject) => { finish = reject; void resolve })
  })
  await mount()
  await send('Draft a construction claim')
  const pending = host.querySelector('.pending-exchange')!
  expect(pending.querySelector('.status-trail')!.textContent).toContain('Gathering evidence for: claim draft')
  expect(pending.querySelector('[role="status"]')!.textContent).toContain('Writing the claim draft')
  await act(async () => finish(new Error('stop') as never))
})


it('a starter card fills the composer with the cursor at the end and does not send', async () => {
  await mount()
  await act(async () => host.querySelector<HTMLButtonElement>('.starter-card')!.click())
  await act(async () => { await new Promise((resolve) => requestAnimationFrame(() => resolve(null))) })
  const box = host.querySelector<HTMLTextAreaElement>('#question')!
  expect(box.value).toBe('How many windows are there?')
  expect(box.selectionStart).toBe(box.value.length)
  expect(api.askQuestion).not.toHaveBeenCalled()
  expect(api.createChat).not.toHaveBeenCalled()
})

it('hides the empty state once a send has failed', async () => {
  api.askQuestion.mockRejectedValueOnce(new Error('boom'))
  await mount()
  expect(host.querySelector('.welcome')).not.toBeNull()
  await send('Hello there')
  expect(host.querySelector('.welcome')).toBeNull()
})

function emitQuestion(chatId: string) {
  for (const fn of live.listeners) fn({ type: 'chat.message', chat_id: chatId, message_id: 'm', role: 'user', text: 'Hello from the laptop' })
}

it('a stranger chat never raises the another-device notice or opens, even with Follow on', async () => {
  await mount()
  await act(async () => setFollow(true))
  window.location.hash = '#/chat'
  await act(async () => emitQuestion('strangers-chat'))
  expect(window.location.hash).toBe('#/chat')
  expect(document.querySelector('[data-testid="follow-banner"]')).toBeNull()
})

it('a known chat opens with Follow on, and nothing happens with Follow off', async () => {
  await mount()
  rememberChat('laptop-chat')
  await act(async () => setFollow(false))
  window.location.hash = '#/chat'
  await act(async () => emitQuestion('laptop-chat'))
  expect(window.location.hash).toBe('#/chat')
  expect(document.querySelector('[data-testid="follow-banner"]')).toBeNull()
  await act(async () => setFollow(true))
  await act(async () => emitQuestion('laptop-chat'))
  expect(window.location.hash).toBe('#/chat?chat=laptop-chat')
})

it('a pair.chat proof for this device\'s code opens the chat before its first message; a wrong proof or Follow off does not', async () => {
  const { addPairing } = await import('../lib/pairing')
  const { createHash } = await import('node:crypto')
  await mount()
  addPairing('abc12345')
  const proof = createHash('sha256').update('abc12345:proof-chat').digest('hex').slice(0, 16)
  const emitProof = (chatId: string, value: string) => { for (const fn of live.listeners) fn({ type: 'pair.chat', chat_id: chatId, proof: value }) }
  await act(async () => setFollow(true))
  window.location.hash = '#/chat'
  await act(async () => emitProof('proof-chat', 'deadbeefdeadbeef'))
  expect(window.location.hash).toBe('#/chat')
  await act(async () => setFollow(false))
  await act(async () => emitProof('proof-chat', proof))
  expect(window.location.hash).toBe('#/chat')
  await act(async () => setFollow(true))
  await act(async () => emitProof('proof-chat', proof))
  expect(window.location.hash).toBe('#/chat?chat=proof-chat')
})
