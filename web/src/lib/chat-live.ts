import { liveSocketUrl } from './live-url'
export type ChatLiveEvent =
  | { type: 'chat.message'; chat_id: string; message_id: string; role: string }
  | { type: 'chat.status'; chat_id: string; text: string }
  | { type: 'connected' }
  | { type: 'disconnected' }

export function decodeChatEvent(raw: unknown): Extract<ChatLiveEvent, { chat_id: string }> | null {
  if (typeof raw !== 'string') return null
  let event: Record<string, unknown>
  try { event = JSON.parse(raw) } catch { return null }
  if (!event || typeof event !== 'object' || typeof event.chat_id !== 'string' || !event.chat_id) return null
  if (event.type === 'chat.message' && typeof event.message_id === 'string' && typeof event.role === 'string')
    return { type: event.type, chat_id: event.chat_id, message_id: event.message_id, role: event.role }
  if (event.type === 'chat.status' && typeof event.text === 'string')
    return { type: event.type, chat_id: event.chat_id, text: event.text }
  return null
}

/** Shared by chat and overview. The existing scene channel decodes only scene events. */
export function createChatLiveClient(options: { url?: string; connect?: (url: string) => WebSocket } = {}) {
  const listeners = new Set<(event: ChatLiveEvent) => void>()
  let socket: WebSocket | null = null
  let retry: ReturnType<typeof setTimeout> | undefined
  let attempt = 0
  let suspended = false
  function emit(event: ChatLiveEvent) { for (const listener of listeners) listener(event) }
  function reconnect() {
    if (suspended || retry !== undefined || !listeners.size) return
    retry = setTimeout(() => { retry = undefined; connect() }, Math.min(250 * 2 ** Math.min(attempt++, 6), 10_000))
  }
  function connect() {
    if (suspended || socket || retry !== undefined || !listeners.size) return
    try {
      const url = options.url ?? liveSocketUrl()
      const connection = (options.connect ?? ((url) => new WebSocket(url)))(url)
      socket = connection
      connection.addEventListener('open', () => {
        if (socket !== connection) return
        attempt = 0
        // Refetch snapshots on every reconnect so missed notifications are recovered.
        emit({ type: 'connected' })
      })
      connection.addEventListener('message', (message) => {
        if (socket !== connection) return
        const event = decodeChatEvent(message.data)
        if (event) emit(event)
        else if (message.data === '{"type": "ping"}' || message.data === '{"type":"ping"}') {
          if (connection.readyState === 1) connection.send(JSON.stringify({ type: 'pong' }))
        }
      })
      connection.addEventListener('close', () => {
        if (socket !== connection) return
        socket = null
        emit({ type: 'disconnected' })
        reconnect()
      })
      connection.addEventListener('error', () => { if (socket === connection) connection.close() })
    } catch { reconnect() }
  }
  function disconnect() {
    if (retry !== undefined) clearTimeout(retry)
    retry = undefined
    const previous = socket
    socket = null
    previous?.close()
    if (previous) emit({ type: 'disconnected' })
  }
  function suspend() { suspended = true; disconnect() }
  function resume() {
    if (document.visibilityState === 'hidden' || navigator.onLine === false) return
    suspended = false
    attempt = 0
    if (retry !== undefined) clearTimeout(retry)
    retry = undefined
    connect()
  }
  function visibility() { if (document.visibilityState === 'hidden') suspend(); else resume() }
  function watchPage(watch: boolean) {
    if (typeof window === 'undefined') return
    const method = watch ? 'addEventListener' : 'removeEventListener'
    window[method]('pagehide', suspend)
    window[method]('pageshow', resume)
    window[method]('offline', suspend)
    window[method]('online', resume)
    document[method]('visibilitychange', visibility)
  }
  return {
    subscribe(listener: (event: ChatLiveEvent) => void) {
      if (!listeners.size) watchPage(true)
      listeners.add(listener)
      if (socket?.readyState === 1) listener({ type: 'connected' })
      connect()
      return () => {
        listeners.delete(listener)
        if (listeners.size) return
        watchPage(false)
        disconnect()
        suspended = false
        attempt = 0
      }
    },
  }
}

export const chatLive = createChatLiveClient()
