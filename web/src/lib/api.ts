import type { Answer, ChangeEntry, Comparison, Document, IngestStatus, PlanMap, SavedChat, TraceStep, UploadReceipt } from './types'

type Mode = 'auto' | 'real' | 'demo'
type StreamCallbacks = { onStatus: (text: string) => void; onTrace: (trace: TraceStep) => void; onDelta?: (text: string) => void }

class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly empty: boolean) { super(message) }
}

/** The server itself reported a failed answer: nothing to recover from the saved chat. */
class ServerAnswerError extends Error {}

type RetryListener = (message: string) => void
const retryMessages = new Map<symbol, string>()
const retryListeners = new Set<RetryListener>()
export const retryMessage = () => [...retryMessages.values()][0] || ''
export function subscribeApiRetry(listener: RetryListener) {
  retryListeners.add(listener)
  listener(retryMessage())
  return () => { retryListeners.delete(listener) }
}
function publishRetry(key: symbol, message: string) {
  if (message) retryMessages.set(key, message)
  else retryMessages.delete(key)
  for (const listener of retryListeners) listener(retryMessage())
}

function retryDelay(response: Response) {
  const value = response.headers.get('Retry-After')?.trim()
  if (!value) return 1_000
  const seconds = Number(value)
  if (Number.isFinite(seconds) && seconds >= 0) return seconds * 1_000
  const date = Date.parse(value)
  return Number.isFinite(date) ? Math.max(0, date - Date.now()) : 1_000
}

async function waitToRetry(ms: number, signal: AbortSignal | null | undefined, update: (seconds: number) => void) {
  signal?.throwIfAborted()
  const deadline = Date.now() + ms
  update(Math.ceil(ms / 1_000))
  await new Promise<void>((resolve, reject) => {
    const interval = setInterval(() => update(Math.max(0, Math.ceil((deadline - Date.now()) / 1_000))), 1_000)
    const finish = () => { clearTimeout(timer); clearInterval(interval); signal?.removeEventListener('abort', abort) }
    const abort = () => { finish(); reject(signal?.reason ?? new DOMException('Aborted', 'AbortError')) }
    const timer = setTimeout(() => { finish(); resolve() }, ms)
    signal?.addEventListener('abort', abort, { once: true })
  })
}

/** Retry rejected rate-limited requests, and safe reads during a backend restart. */
export function createRetryTransport(transport: typeof fetch = (...args) => fetch(...args)): typeof fetch {
  return async (input, init) => {
    const method = (init?.method || (input instanceof Request ? input.method : 'GET')).toUpperCase()
    const signal = init?.signal ?? (input instanceof Request ? input.signal : undefined)
    const key = Symbol('request')
    try {
      for (let attempt = 0; ; attempt++) {
        signal?.throwIfAborted()
        // Keep a replayable Request body when callers supply a Request rather than RequestInit.
        const response = await transport(input instanceof Request ? input.clone() : input, init)
        const limited = response.status === 429
        const restarting = method === 'GET' && (response.status === 502 || response.status === 503)
        if (!limited && !restarting) return response
        if (attempt === 2) {
          if (limited) throw new ApiError('Too many requests. Please try again shortly.', 429, false)
          return response
        }
        await response.body?.cancel().catch(() => {})
        await waitToRetry(limited ? retryDelay(response) : 1_000, signal,
          (seconds) => { if (limited) publishRetry(key, `Too many requests, retrying in ${seconds}s`) })
      }
    } finally { publishRetry(key, '') }
  }
}

export const apiFetch = createRetryTransport()

/** A POST stream may split UTF-8, JSON and CRLF across arbitrary network chunks. */
export async function readAnswerStream(response: Response, callbacks: StreamCallbacks, idleMs = 180_000): Promise<Answer> {
  if (!response.body) throw new Error('The answer stream could not be opened.')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let answer: Answer | undefined
  function consume(block: string) {
    const lines = block.split('\n')
    const event = lines.find((line) => line.startsWith('event:'))?.slice(6).trim()
    const data = lines.filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trimStart()).join('\n')
    if (!data || !['status', 'trace', 'delta', 'answer', 'error'].includes(event ?? '')) return
    const payload = JSON.parse(data)
    if (event === 'error') throw new ServerAnswerError(payload.detail || 'The answer could not be completed. Please try again.')
    if (event === 'status' && typeof payload.text === 'string') callbacks.onStatus(payload.text)
    if (event === 'trace') callbacks.onTrace(payload as TraceStep)
    if (event === 'delta' && typeof payload.text === 'string') callbacks.onDelta?.(payload.text)
    if (event === 'answer') answer = payload as Answer
  }
  try {
    while (true) {
      // A server restart can leave the socket open and silent: give up after idleMs without any event so the UI offers Retry instead of thinking forever.
      let timer: ReturnType<typeof setTimeout> | undefined
      const idle = new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new Error('The connection dropped before the answer arrived. Please try again.')), idleMs) })
      const { value, done } = await Promise.race([reader.read(), idle]).finally(() => clearTimeout(timer))
      buffer = (buffer + decoder.decode(value, { stream: !done })).replace(/\r\n/g, '\n')
      let boundary: number
      while ((boundary = buffer.indexOf('\n\n')) !== -1) {
        consume(buffer.slice(0, boundary))
        buffer = buffer.slice(boundary + 2)
      }
      if (done) { if (buffer.trim()) consume(buffer); break }
    }
  } finally {
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
  if (!answer) throw new Error('The response ended before an answer arrived. Please try again.')
  return answer
}

export class WorkspaceApi {
  isDemo: boolean
  private transport: typeof fetch
  constructor(private mode: Mode = 'auto', transport: typeof fetch = (...args) => fetch(...args)) {
    this.isDemo = mode === 'demo'
    this.transport = createRetryTransport(transport)
  }

  private async request(path: string, init?: RequestInit): Promise<Response> {
    let response: Response
    if (this.isDemo) {
      const { handleMockRequest } = await import('../mock/handler')
      const mocked = await handleMockRequest(new Request(new URL(path, 'http://localhost'), init))
      if (!mocked) throw new Error('This action is unavailable in the offline demo.')
      response = mocked
    } else {
      response = await this.transport(path, init)
    }
    if (!response.ok) {
      const body = await response.text()
      let detail = `Request failed (${response.status}). Please try again.`
      try { detail = JSON.parse(body).detail || detail } catch { /* Proxy errors may have no JSON body. */ }
      throw new ApiError(detail, response.status, !body.trim())
    }
    return response
  }

  private async retryDocuments(): Promise<Response> {
    const key = Symbol('docs')
    try {
      for (let attempt = 1; ; attempt++) {
        publishRetry(key, `Server is busy, retrying… (${attempt})`)
        await new Promise((resolve) => setTimeout(resolve, Math.min(1_000 * 2 ** Math.min(attempt - 1, 3), 8_000)))
        try { return await this.request('/api/docs', { signal: AbortSignal.timeout(20_000) }) } catch { /* keep retrying */ }
      }
    } finally { publishRetry(key, '') }
  }

  async getDocuments(): Promise<Document[]> {
    let response: Response
    try {
      try {
        response = await this.request('/api/docs', { signal: AbortSignal.timeout(10_000) })
      } catch (first) {
        // One slow or dropped call must not pin the whole session to offline demo; retry once, longer.
        const slow = first instanceof TypeError || (first instanceof DOMException && first.name === 'TimeoutError')
        if (this.mode !== 'auto' || !slow) throw first
        response = await this.request('/api/docs', { signal: AbortSignal.timeout(20_000) })
      }
    } catch (error) {
      const unreachable = error instanceof TypeError || (error instanceof DOMException && error.name === 'TimeoutError') ||
        (error instanceof ApiError && ([502, 504].includes(error.status) || (error.status === 500 && error.empty)))
      if (this.mode !== 'auto' || !unreachable) throw error
      if (!allowDemoFallback) {
        // Production: a real visitor must never land in the toy offline demo. Keep retrying with backoff.
        response = await this.retryDocuments()
      } else {
        // Dev/test: choose the offline dataset before selecting docs; never substitute fake answers for real docs.
        this.isDemo = true
        response = await this.request('/api/docs')
      }
    }
    const data = await response.json() as { sources: { docs: Document[] }[] }
    return data.sources.flatMap((source) => source.docs)
  }

  async createChat(docIds: string[], title: string, projectId?: string | null): Promise<string> {
    const response = await this.request('/api/chats', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ doc_ids: docIds, title, ...(projectId ? { project_id: projectId } : {}) }),
    })
    const chat = await response.json() as { id: string }
    return chat.id
  }

  async getChat(id: string, signal?: AbortSignal): Promise<SavedChat> {
    const response = await this.request(`/api/chats/${encodeURIComponent(id)}`, { signal })
    return response.json() as Promise<SavedChat>
  }

  async getChanges(signal?: AbortSignal): Promise<ChangeEntry[]> {
    // The offline demo lists only designs saved in this session (mock API); there are no real revision series.
    const response = await this.request('/api/changes', { signal })
    return ((await response.json()) as { changes: ChangeEntry[] }).changes
  }

  async getComparison(id: string, signal?: AbortSignal): Promise<Comparison> {
    const response = await this.request(`/api/changes/${encodeURIComponent(id)}`, { signal })
    const data = await response.json() as Comparison
    if (!data.image || !data.v1 || !data.v2 || !Array.isArray(data.changes)) throw new Error('Comparison images are not available for this change.')
    return data
  }

  /** Any JSON GET through this client (the offline demo answers from the mock API). */
  async fetchJson<T>(path: string, signal?: AbortSignal): Promise<T> {
    return (await this.request(path, { signal })).json() as Promise<T>
  }

  async getDocument(docId: string): Promise<Document> {
    const response = await this.request(`/api/docs/${encodeURIComponent(docId)}`)
    return response.json() as Promise<Document>
  }

  async getPlanMap(docId: string, page: number, signal?: AbortSignal): Promise<PlanMap> {
    const response = await this.request(`/api/docs/${encodeURIComponent(docId)}/planmap/${page}`, { signal })
    return response.json() as Promise<PlanMap>
  }

  async getDocumentTags(docId: string, signal?: AbortSignal): Promise<Record<string, string>> {
    try {
      const response = await this.request(`/api/docs/${encodeURIComponent(docId)}/files/scene.json`, { signal })
      const scene = await response.json() as { items: Record<string, { tag?: string }> }
      return Object.fromEntries(Object.entries(scene.items).flatMap(([id, item]) => item.tag ? [[id, item.tag]] : []))
    } catch (error) {
      if (signal?.aborted) throw error
      // A drawing can have evidence without a 3D scene or stable tags.
      return {}
    }
  }

  async uploadDocument(file: File): Promise<UploadReceipt> {
    const body = new FormData()
    body.append('file', file)
    const response = await this.request('/api/upload', { method: 'POST', body })
    return response.json() as Promise<UploadReceipt>
  }

  async getIngestStatus(docId: string, signal: AbortSignal): Promise<IngestStatus> {
    const response = await this.request(`/api/docs/${encodeURIComponent(docId)}/ingest`, { signal })
    return response.json() as Promise<IngestStatus>
  }

  async hasScene(docId: string, signal: AbortSignal): Promise<boolean> {
    try {
      // Check the existing artifact; /scene may trigger extrusion on future servers.
      await this.request(`/api/docs/${encodeURIComponent(docId)}/files/scene.json`, { signal })
      return true
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return false
      throw error
    }
  }

  async getPageImage(docId: string, page: number, signal: AbortSignal): Promise<Blob> {
    const response = await this.request(`/api/docs/${encodeURIComponent(docId)}/pages/${page}/image`, { signal })
    return response.blob()
  }

  /**
   * One Send = one POST, never re-posted. The client message id lets the server answer a duplicate
   * once. If the stream drops, the answer is recovered by polling the saved chat, not by asking again.
   */
  async askQuestion(chatId: string, content: string, docIds: string[], callbacks: StreamCallbacks): Promise<Answer> {
    const clientMessageId = globalThis.crypto?.randomUUID?.() ?? `m-${Date.now()}-${Math.random().toString(36).slice(2)}`
    const sentAt = Date.now()
    const response = await this.request(`/api/chats/${encodeURIComponent(chatId)}/messages`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({ content, doc_ids: docIds, client_message_id: clientMessageId }),
    })
    try {
      return await readAnswerStream(response, callbacks)
    } catch (error) {
      if (error instanceof ServerAnswerError) throw error
      // The server accepted the question but the stream dropped: fetch the saved answer, never ask again.
      const recovered = await this.awaitSavedAnswer(chatId, sentAt, content)
      if (recovered) return recovered
      throw error
    }
  }

  /** Poll GET /api/chats/{id} for the answer to the question that was just sent (created since `sentAt`, 60 s clock tolerance). */
  async awaitSavedAnswer(chatId: string, sentAt: number, content: string, maxMs = 180_000, everyMs = 3_000): Promise<Answer | null> {
    for (let waited = 0; waited <= maxMs; waited += everyMs) {
      try {
        const chat = await this.getChat(chatId)
        const at = (m: { created_at?: string }) => (m.created_at ? Date.parse(m.created_at) : Infinity)
        let index = -1
        chat.messages.forEach((m, i) => { if (m.role === 'user' && m.content === content && at(m) >= sentAt - 60_000) index = i })
        const done = index < 0 ? undefined : chat.messages.slice(index + 1).find((m) => m.role === 'assistant' && m.answer)
        if (done?.answer) return done.answer
      } catch { /* keep polling */ }
      await new Promise((resolve) => setTimeout(resolve, everyMs))
    }
    return null
  }
}

const setting = import.meta.env?.VITE_USE_MOCK  // env is undefined when e2e specs import helpers from this module in Node
/** The offline mock only exists outside production builds (or when explicitly forced). */
const allowDemoFallback = !import.meta.env?.PROD || import.meta.env?.VITE_ALLOW_DEMO === 'true'
export const workspaceApi = new WorkspaceApi(setting === 'true' ? 'demo' : setting === 'false' ? 'real' : 'auto')
