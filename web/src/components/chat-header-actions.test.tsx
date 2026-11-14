// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ChatHeaderActions } from './chat-header-actions'

let host: HTMLDivElement
let root: Root

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  window.history.replaceState(null, '', '#/chat')
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ chats: [] }) })))
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
})

afterEach(async () => {
  await act(async () => root.unmount())
  host.remove()
  vi.unstubAllGlobals()
})

it('starts a new chat from empty History and closes the popover and share message', async () => {
  const onNew = vi.fn()
  await act(async () => root.render(<ChatHeaderActions chatId={null} onNew={onNew} />))
  await act(async () => host.querySelector<HTMLButtonElement>('[aria-label="Share"]')!.click())
  expect(host.textContent).toContain('Start a chat to share a link.')
  await act(async () => host.querySelector<HTMLButtonElement>('[aria-label="History"]')!.click())
  const history = host.querySelector('[role="dialog"]')!
  expect(history.textContent).toContain('No saved chats yet.')
  const action = [...history.querySelectorAll('button')].find((button) => button.textContent === 'New chat')!
  expect(action).toBeTruthy()
  await act(async () => action.click())
  expect(onNew).toHaveBeenCalledOnce()
  expect(host.querySelector('[role="dialog"]')).toBeNull()
  expect(host.querySelector('[aria-label="History"]')?.getAttribute('aria-expanded')).toBe('false')
  expect(host.querySelector('.chat-action-toast')).toBeNull()
})
