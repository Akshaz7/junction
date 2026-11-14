// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

function fakeStorage() {
  const data = new Map<string, string>()
  return { getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => { data.set(k, v) }, removeItem: (k: string) => { data.delete(k) }, clear: () => data.clear() }
}

describe('pairing', () => {
  beforeEach(() => {
    vi.resetModules()
    Object.defineProperty(window, 'localStorage', { value: fakeStorage(), configurable: true })
  })
  afterEach(() => vi.unstubAllGlobals())

  it('stores codes, turns follow on, persists and unpairs', async () => {
    const p = await import('./pairing')
    const follow = await import('./chat-follow')
    expect(p.isPaired()).toBe(false)
    const code = p.newPairCode()
    expect(code).toMatch(/^[a-z0-9]{8}$/)
    expect(p.addPairing(code)).toBe(true)
    expect(p.addPairing('bad!')).toBe(false)
    expect(p.getPairings()).toEqual([code])
    follow.setFollow(false)
    p.addPairing(code)
    expect(follow.getFollow()).toBe(true)
    expect(p.ensurePairCode()).toBe(code)
    p.unpair()
    expect(p.isPaired()).toBe(false)
  })

  it('parses the pair link', async () => {
    const p = await import('./pairing')
    expect(p.pairCodeFromHash(`#/pair?code=abc12345`)).toBe('abc12345')
    expect(p.pairCodeFromHash('#/chat')).toBeNull()
    expect(p.pairLink('abc12345', 'https://x.test')).toBe('https://x.test/#/pair?code=abc12345')
  })

  it('the QR payload opens the native app, the visible link stays https', async () => {
    const p = await import('./pairing')
    expect(p.pairAppLink('abc12345')).toBe('hologram://pair?code=abc12345')
    expect(p.pairLink('abc12345', 'https://x.test')).toMatch(/^https:/)
  })

  it('filter: known chat passes, paired chat passes via server, stranger fails', async () => {
    const p = await import('./pairing')
    const known = await import('./known-chats')
    p.addPairing('abc12345')
    known.rememberChat('mine')
    const fetchMock = vi.fn(async (url: string) => ({ ok: true, json: async () => ({ paired: String(url).includes('/theirs') }) }))
    vi.stubGlobal('fetch', fetchMock)
    expect(await p.isPairedChat('mine')).toBe(true)
    expect(fetchMock).not.toHaveBeenCalled()
    expect(await p.isPairedChat('theirs')).toBe(true)
    expect(known.isKnownChat('theirs')).toBe(true)
    expect(await p.isPairedChat('stranger')).toBe(false)
  })

  it('fails open only when asked to and the server cannot answer', async () => {
    const p = await import('./pairing')
    p.addPairing('abc12345')
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('timeout') }))
    expect(await p.isPairedChat('late')).toBe(false)
    expect(await p.isPairedChat('late', { failOpen: true })).toBe(true)
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ paired: false }) })))
    expect(await p.isPairedChat('stranger', { failOpen: true })).toBe(false)
  })

  it('a live proof for one of our codes marks the chat as known without a server call', async () => {
    const p = await import('./pairing')
    const known = await import('./known-chats')
    p.addPairing('abc12345')
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const { createHash } = await import('node:crypto')
    const good = createHash('sha256').update('abc12345:chat-z').digest('hex').slice(0, 16)
    expect(await p.acceptPairProof('chat-z', 'deadbeefdeadbeef')).toBe(false)
    expect(known.isKnownChat('chat-z')).toBe(false)
    expect(await p.acceptPairProof('chat-z', good)).toBe(true)
    expect(known.isKnownChat('chat-z')).toBe(true)
    expect(await p.isPairedChat('chat-z')).toBe(true)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('unpaired device never asks the server', async () => {
    const p = await import('./pairing')
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    expect(await p.isPairedChat('x')).toBe(false)
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
