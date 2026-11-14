// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ConnectionPill } from './connection-pill'
import { createChatLiveClient } from '../lib/chat-live'
import { createRetryTransport } from '../lib/api'

class Socket extends EventTarget {
  readyState = 0
  open() { this.readyState = 1; this.dispatchEvent(new Event('open')) }
  close() { this.readyState = 3; this.dispatchEvent(new Event('close')) }
}
let host: HTMLDivElement
let root: Root
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.useFakeTimers()
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
})
afterEach(async () => {
  await act(async () => root.unmount())
  host.remove()
  vi.useRealTimers()
})

describe('connection feedback', () => {
  it('reconnects with increasing backoff, shows the pill across hidden routes and clears it on open', async () => {
    const sockets: Socket[] = []
    const connect = vi.fn(() => { const socket = new Socket(); sockets.push(socket); return socket as unknown as WebSocket })
    const live = createChatLiveClient({ url: 'ws://test/ws', connect })
    await act(async () => root.render(<section hidden><ConnectionPill live={live} /></section>))
    await act(async () => sockets[0].open())
    expect(document.querySelector('.connection-pill')).toBeNull()
    await act(async () => sockets[0].close())
    expect(document.querySelector('.connection-pill')?.textContent).toBe('Reconnecting…')
    expect(document.querySelector('.connection-pill')?.parentElement).toBe(document.body)
    await act(async () => { await vi.advanceTimersByTimeAsync(250); sockets[1].close() })
    await act(async () => vi.advanceTimersByTimeAsync(499))
    expect(connect).toHaveBeenCalledTimes(2)
    await act(async () => { await vi.advanceTimersByTimeAsync(1); sockets[2].open() })
    expect(connect).toHaveBeenCalledTimes(3)
    expect(document.querySelector('.connection-pill')).toBeNull()
    await act(async () => root.unmount())
    expect(vi.getTimerCount()).toBe(0)
    // Give afterEach a live root to unmount.
    root = createRoot(host)
  })

  it('shows a rate-limit countdown and clears it when a request recovers', async () => {
    await act(async () => root.render(<ConnectionPill enabled={false} />))
    const transport = vi.fn<typeof fetch>().mockResolvedValueOnce(new Response('', { status: 429, headers: { 'Retry-After': '2' } })).mockResolvedValueOnce(Response.json({ ok: true }))
    let result: Promise<Response>
    await act(async () => { result = createRetryTransport(transport)('/api/docs'); await vi.advanceTimersByTimeAsync(0) })
    expect(document.querySelector('.connection-pill')?.textContent).toBe('Too many requests, retrying in 2s')
    await act(async () => vi.advanceTimersByTimeAsync(1_000))
    expect(document.querySelector('.connection-pill')?.textContent).toBe('Too many requests, retrying in 1s')
    await act(async () => { await vi.advanceTimersByTimeAsync(1_000); await result! })
    expect(document.querySelector('.connection-pill')).toBeNull()
  })
})
