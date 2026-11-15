import { liveSocketUrl } from './live-url'
import type { TraceStep } from './types'
export type ChatLiveEvent =
  | { type: 'chat.message'; chat_id: string; message_id: string; role: string; text?: string }
  | { type: 'chat.status'; chat_id: string; text: string }
  | { type: 'chat.trace'; chat_id: string; step: TraceStep }
  | { type: 'chat.delta'; chat_id: string; text: string }
  | { type: 'chat.done'; chat_id: string }
  | { type: 'pair.chat'; chat_id: string; proof: string }
  | { type: 'pair.joined'; proof: string }
  | { type: 'connected' }
  | { type: 'disconnected' }

export function decodeChatEvent(raw: unknown): Exclude<ChatLiveEvent, { type: 'connected' | 'disconnected' }> | null {
  if (typeof raw !== 'string') return null
  let event: Record<string, unknown>
  try { event = JSON.parse(raw) } catch { return null }
  if (event && event.type === 'pair.joined' && typeof event.proof === 'string') return { type: 'pair.joined', proof: event.proof }
  if (!event || typeof event !== 'object' || typeof event.chat_id !== 'string' || !event.chat_id) return null
  if (event.type === 'chat.message' && typeof event.message_id === 'string' && typeof event.role === 'string')
    return { type: event.type, chat_id: event.chat_id, message_id: event.message_id, role: event.role,
      ...(typeof event.text === 'string' ? { text: event.text } : {}) }
  if (event.type === 'chat.trace' && event.step && typeof event.step === 'object' && !Array.isArray(event.step))
    return { type: event.type, chat_id: event.chat_id, step: event.step as TraceStep }
  if (event.type === 'chat.delta' && typeof event.text === 'string') return { type: event.type, chat_id: event.chat_id, text: event.text }
  if (event.type === 'pair.chat' && typeof event.proof === 'string') return { type: event.type, chat_id: event.chat_id, proof: event.proof }
  if (event.type === 'chat.done') return { type: event.type, chat_id: event.chat_id }
  if (event.type === 'chat.status' && typeof event.text === 'string')
    return { type: event.type, chat_id: event.chat_id, text: event.text }
  return null
}

/** What a listener wants from the server (F-WSSCOPE). No scope = everything (legacy). `{}` = no chat events at all,
 * only connection and pair events. `chatIds` = the full live stream of those chats. `summaries` = just the one
 * chat.message per message of any chat (overview list, Follow). */
export type LiveScope = { chatIds?: string[]; summaries?: boolean }

export function inScope(scope: LiveScope | undefined, event: ChatLiveEvent): boolean {
  if (!scope || !event.type.startsWith('chat.') || !('chat_id' in event)) return true
  return !!scope.chatIds?.includes(event.chat_id) || (!!scope.summaries && event.type === 'chat.message')
}

/** Union of all listener scopes, or null when any listener is unscoped (then nothing is sent: the server streams everything). */
export function mergeScopes(scopes: Iterable<LiveScope | undefined>): { chat_ids: string[]; summaries: boolean } | null {
  const ids = new Set<string>()
  let summaries = false
  for (const scope of scopes) {
    if (!scope) return null
    for (const id of scope.chatIds ?? []) ids.add(id)
    summaries ||= !!scope.summaries
  }
  return { chat_ids: [...ids].sort(), summaries }
}

/** Shared by chat and overview. The existing scene channel decodes only scene events. */
export function createChatLiveClient(options: { url?: string; connect?: (url: string) => WebSocket } = {}) {
  const listeners = new Map<(event: ChatLiveEvent) => void, LiveScope | undefined>()
  let lastSent = ''
  let socket: WebSocket | null = null
  let retry: ReturnType<typeof setTimeout> | undefined
  let attempt = 0
  let stable: ReturnType<typeof setTimeout> | undefined
  let suspended = false
  function emit(event: ChatLiveEvent) { for (const [listener, scope] of [...listeners]) if (inScope(scope, event)) listener(event) }
  function sendScope(connection: WebSocket | null = socket) {
    const merged = mergeScopes(listeners.values())
    const text = merged ? JSON.stringify({ type: 'subscribe', ...merged }) : ''
    if (!merged || !connection || connection.readyState !== 1 || text === lastSent) return
    lastSent = text
    try { connection.send(text) } catch { lastSent = '' }
  }
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
        // A flapping socket must keep backing off: only forget failures once the link stayed up for 5 s.
        clearTimeout(stable)
        stable = setTimeout(() => { if (socket === connection) attempt = 0 }, 5000)
        lastSent = ''
        sendScope(connection)
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
        clearTimeout(stable)
        socket = null
        emit({ type: 'disconnected' })
        reconnect()
      })
      connection.addEventListener('error', () => { if (socket === connection) connection.close() })
    } catch { reconnect() }
  }
  function disconnect() {
    clearTimeout(stable)
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
    subscribe(listener: (event: ChatLiveEvent) => void, scope?: LiveScope) {
      if (!listeners.size) watchPage(true)
      listeners.set(listener, scope)
      sendScope()
      if (socket?.readyState === 1) listener({ type: 'connected' })
      connect()
      return () => {
        listeners.delete(listener)
        if (listeners.size) { sendScope(); return }
        watchPage(false)
        disconnect()
        suspended = false
        attempt = 0
      }
    },
  }
}

export const chatLive = createChatLiveClient()
