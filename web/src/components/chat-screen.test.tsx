// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { demoDocument } from '../mock/handler'

const api = vi.hoisted(() => ({ createChat: vi.fn(), askQuestion: vi.fn(), getChat: vi.fn() }))
vi.mock('../lib/api', async (original) => ({ ...(await original<typeof import('../lib/api')>()), workspaceApi: { ...api, isDemo: false } }))
import { ChatScreen } from './chat-screen'

let host: HTMLDivElement
let root: Root

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  window.history.replaceState(null, '', '#/chat')
  vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }))
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
