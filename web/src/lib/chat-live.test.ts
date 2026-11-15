import { afterEach, describe, expect, it, vi } from 'vitest'
import { createChatLiveClient, decodeChatEvent, inScope, mergeScopes } from './chat-live'

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

  it('decodes in-progress trace and done events and the question text on user messages', () => {
    const step = { step: 'x', detail: 'd', ms: 3 }
    expect(decodeChatEvent(JSON.stringify({ type: 'chat.trace', chat_id: 'c', step }))).toEqual({ type: 'chat.trace', chat_id: 'c', step })
    expect(decodeChatEvent(JSON.stringify({ type: 'chat.delta', chat_id: 'c', text: 'There are' }))).toEqual({ type: 'chat.delta', chat_id: 'c', text: 'There are' })
    expect(decodeChatEvent(JSON.stringify({ type: 'chat.delta', chat_id: 'c' }))).toBeNull()
    expect(decodeChatEvent(JSON.stringify({ type: 'chat.done', chat_id: 'c' }))).toEqual({ type: 'chat.done', chat_id: 'c' })
    expect(decodeChatEvent(JSON.stringify({ ...message, text: 'How many?' }))).toEqual({ ...message, text: 'How many?' })
    expect(decodeChatEvent(JSON.stringify({ type: 'chat.trace', chat_id: 'c', step: [] }))).toBeNull()
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

  it('scopes chat events per listener and tells the server the union of scopes (F-WSSCOPE)', () => {
    vi.useFakeTimers()
    const sockets: Socket[] = []
    const connect = vi.fn(() => { const socket = new Socket(); sockets.push(socket); return socket as unknown as WebSocket })
    const client = createChatLiveClient({ url: 'ws://test/ws', connect })
    const mine = vi.fn(), overview = vi.fn(), pill = vi.fn()
    const stopMine = client.subscribe(mine, { chatIds: ['chat-a'] })
    client.subscribe(pill, {})
    sockets[0].open()
    expect(sockets[0].sent).toEqual(['{"type":"subscribe","chat_ids":["chat-a"],"summaries":false}'])
    const stopOverview = client.subscribe(overview, { summaries: true })
    expect(sockets[0].sent.at(-1)).toBe('{"type":"subscribe","chat_ids":["chat-a"],"summaries":true}')
    const other = { ...message, chat_id: 'chat-b' }
    sockets[0].receive(JSON.stringify(other))
    sockets[0].receive(JSON.stringify({ type: 'chat.status', chat_id: 'chat-b', text: 'x' }))
    sockets[0].receive(JSON.stringify(message))
    expect(mine.mock.calls.filter(([e]) => e.type?.startsWith('chat.')).map(([e]) => e.chat_id)).toEqual(['chat-a'])
    expect(overview.mock.calls.filter(([e]) => e.type === 'chat.message')).toHaveLength(2)
    expect(overview.mock.calls.some(([e]) => e.type === 'chat.status')).toBe(false)
    expect(pill.mock.calls.some(([e]) => e.type?.startsWith('chat.'))).toBe(false)
    stopOverview()
    expect(sockets[0].sent.at(-1)).toBe('{"type":"subscribe","chat_ids":["chat-a"],"summaries":false}')
    // An unscoped (legacy) listener means the server keeps streaming everything: no scope is sent for it.
    const legacy = vi.fn()
    const sentBefore = sockets[0].sent.length
    client.subscribe(legacy)
    expect(sockets[0].sent).toHaveLength(sentBefore)
    sockets[0].receive(JSON.stringify(other))
    expect(legacy).toHaveBeenLastCalledWith(other)
    stopMine()
  })

  it('resends the subscription after a reconnect and unions scopes', () => {
    vi.useFakeTimers()
    const sockets: Socket[] = []
    const connect = vi.fn(() => { const socket = new Socket(); sockets.push(socket); return socket as unknown as WebSocket })
    const client = createChatLiveClient({ url: 'ws://test/ws', connect })
    client.subscribe(vi.fn(), { chatIds: ['b', 'a'] })
    sockets[0].open()
    sockets[0].close()
    vi.advanceTimersByTime(250)
    sockets[1].open()
    expect(sockets[1].sent).toEqual(['{"type":"subscribe","chat_ids":["a","b"],"summaries":false}'])
    expect(mergeScopes([{ chatIds: ['a'] }, undefined])).toBeNull()
    expect(inScope(undefined, { type: 'chat.done', chat_id: 'x' })).toBe(true)
    expect(inScope({}, { type: 'connected' })).toBe(true)
    expect(inScope({ chatIds: ['x'] }, { type: 'chat.done', chat_id: 'y' })).toBe(false)
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
