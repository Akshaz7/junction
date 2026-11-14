import { afterEach, describe, expect, it, vi } from 'vitest'
import { createChatLiveClient, decodeChatEvent } from './chat-live'

class Socket extends EventTarget {
  readyState = 0
  sent: string[] = []
  open() { this.readyState = 1; this.dispatchEvent(new Event('open')) }
  receive(data: unknown) { this.dispatchEvent(new MessageEvent('message', { data })) }
  send(data: string) { this.sent.push(data) }
  close() { this.readyState = 3; this.dispatchEvent(new Event('close')) }
}
const message = { type: 'chat.message', chat_id: 'chat-a', message_id: 'm-1', role: 'user' }

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

describe('live chat notifications', () => {
  it('decodes server notifications and ignores invalid or unrelated events', () => {
    expect(decodeChatEvent(JSON.stringify(message))).toEqual(message)
    expect(decodeChatEvent(JSON.stringify({ type: 'chat.status', chat_id: 'chat-a', text: 'Thinking…' })))
      .toEqual({ type: 'chat.status', chat_id: 'chat-a', text: 'Thinking…' })
    for (const raw of ['broken', 'null', '[]', '{}', '{"type":"chat.message","chat_id":"x"}', '{"type":"chat.status","chat_id":1,"text":"x"}', '{"type":"scene.highlight","doc_id":"x","item_ids":[]}'])
      expect(decodeChatEvent(raw)).toBeNull()
  })

  it('shares a connection, recovers missed snapshots after reconnect, and releases all resources', () => {
    vi.useFakeTimers()
    const sockets: Socket[] = []
    const connect = vi.fn(() => { const socket = new Socket(); sockets.push(socket); return socket as unknown as WebSocket })
    const client = createChatLiveClient({ url: 'ws://test/ws', connect })
    const a = vi.fn(), b = vi.fn()
    const stopA = client.subscribe(a)
    sockets[0].open()
    const stopB = client.subscribe(b)
    expect(connect).toHaveBeenCalledTimes(1)
    expect(a).toHaveBeenLastCalledWith({ type: 'connected' })
    expect(b).toHaveBeenLastCalledWith({ type: 'connected' })
    sockets[0].receive(JSON.stringify(message))
    expect(a).toHaveBeenLastCalledWith(message)
    expect(b).toHaveBeenLastCalledWith(message)
    sockets[0].receive('{"type": "ping"}')
    expect(sockets[0].sent).toEqual(['{"type":"pong"}'])
    sockets[0].close()
    expect(a).toHaveBeenLastCalledWith({ type: 'disconnected' })
    expect(b).toHaveBeenLastCalledWith({ type: 'disconnected' })
    vi.advanceTimersByTime(250)
    expect(connect).toHaveBeenCalledTimes(2)
    sockets[1].open()
    expect(b).toHaveBeenLastCalledWith({ type: 'connected' })
    stopA()
    expect(sockets[1].readyState).toBe(1)
    stopB()
    expect(sockets[1].readyState).toBe(3)
    vi.advanceTimersByTime(20_000)
    expect(connect).toHaveBeenCalledTimes(2)
  })

  it('retries connection failures and cancels a pending reconnect on unmount', () => {
    vi.useFakeTimers()
    const connect = vi.fn((): WebSocket => { throw new Error('offline') })
    const client = createChatLiveClient({ url: 'ws://test/ws', connect })
    const stop = client.subscribe(() => {})
    vi.advanceTimersByTime(250)
    expect(connect).toHaveBeenCalledTimes(2)
    stop()
    vi.advanceTimersByTime(20_000)
    expect(connect).toHaveBeenCalledTimes(2)
  })

  it('reconnects immediately after background/offline and removes page listeners on release', () => {
    vi.useFakeTimers()
    const page = new EventTarget()
    const document = Object.assign(new EventTarget(), { visibilityState: 'visible' })
    const navigator = { onLine: true }
    vi.stubGlobal('window', page)
    vi.stubGlobal('document', document)
    vi.stubGlobal('navigator', navigator)
    const sockets: Socket[] = []
    const connect = vi.fn(() => { const socket = new Socket(); sockets.push(socket); return socket as unknown as WebSocket })
    const client = createChatLiveClient({ url: 'ws://test/ws', connect })
    const listener = vi.fn()
    const stop = client.subscribe(listener)
    sockets[0].open()
    document.visibilityState = 'hidden'
    document.dispatchEvent(new Event('visibilitychange'))
    page.dispatchEvent(new Event('pagehide'))
    navigator.onLine = false
    page.dispatchEvent(new Event('offline'))
    expect(sockets[0].readyState).toBe(3)
    expect(listener).toHaveBeenLastCalledWith({ type: 'disconnected' })
    vi.advanceTimersByTime(20_000)
    expect(connect).toHaveBeenCalledTimes(1)

    document.visibilityState = 'visible'
    document.dispatchEvent(new Event('visibilitychange'))
    page.dispatchEvent(new Event('pageshow'))
    expect(connect).toHaveBeenCalledTimes(1)
    navigator.onLine = true
    page.dispatchEvent(new Event('online'))
    expect(connect).toHaveBeenCalledTimes(2)
    sockets[1].open()
    expect(listener).toHaveBeenLastCalledWith({ type: 'connected' })
    page.dispatchEvent(new Event('pageshow'))
    expect(connect).toHaveBeenCalledTimes(2)
    sockets[0].receive(JSON.stringify(message))
    expect(listener).toHaveBeenLastCalledWith({ type: 'connected' })

    // Online recovery bypasses a previously scheduled backoff.
    sockets[1].close()
    page.dispatchEvent(new Event('online'))
    expect(connect).toHaveBeenCalledTimes(3)
    sockets[2].open()
    stop()
    page.dispatchEvent(new Event('pageshow'))
    document.dispatchEvent(new Event('visibilitychange'))
    vi.advanceTimersByTime(20_000)
    expect(connect).toHaveBeenCalledTimes(3)
    expect(sockets[2].readyState).toBe(3)
  })
})
