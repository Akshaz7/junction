// @vitest-environment jsdom
import { beforeEach, expect, it } from 'vitest'
import { isKnownChat, rememberChat } from './known-chats'

function fakeStorage() {
  const data = new Map<string, string>()
  Object.defineProperty(window, 'localStorage', { configurable: true, value: {
    getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => { data.set(k, String(v)) },
    removeItem: (k: string) => { data.delete(k) }, clear: () => data.clear() } })
}
beforeEach(() => fakeStorage())

it('knows only chats this browser created or opened', () => {
  expect(isKnownChat('strangers-chat')).toBe(false)
  rememberChat('mine')
  expect(isKnownChat('mine')).toBe(true)
  expect(isKnownChat('strangers-chat')).toBe(false)
  expect(JSON.parse(window.localStorage.getItem('hologram.known-chats')!)).toContain('mine')
})
