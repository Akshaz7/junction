import type { Answer, ChangeEntry, Comparison, Document, IngestStatus, TraceStep, UploadReceipt } from './types'

type Mode = 'auto' | 'real' | 'demo'
type StreamCallbacks = { onStatus: (text: string) => void; onTrace: (trace: TraceStep) => void }

class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly empty: boolean) { super(message) }
}

/** A POST stream may split UTF-8, JSON and CRLF across arbitrary network chunks. */
export async function readAnswerStream(response: Response, callbacks: StreamCallbacks): Promise<Answer> {
  if (!response.body) throw new Error('The answer stream could not be opened.')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let answer: Answer | undefined
  function consume(block: string) {
    const lines = block.split('\n')
    const event = lines.find((line) => line.startsWith('event:'))?.slice(6).trim()
    const data = lines.filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trimStart()).join('\n')
    if (!data || !['status', 'trace', 'answer', 'error'].includes(event ?? '')) return
    const payload = JSON.parse(data)
    if (event === 'error') throw new Error(payload.detail || 'The answer could not be completed. Please try again.')
    if (event === 'status' && typeof payload.text === 'string') callbacks.onStatus(payload.text)
    if (event === 'trace') callbacks.onTrace(payload as TraceStep)
    if (event === 'answer') answer = payload as Answer
  }
  try {
    while (true) {
      const { value, done } = await reader.read()
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
  constructor(private mode: Mode = 'auto', private transport: typeof fetch = (...args) => fetch(...args)) {
    this.isDemo = mode === 'demo'
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

  async getDocuments(): Promise<Document[]> {
    let response: Response
    try {
      response = await this.request('/api/docs', { signal: AbortSignal.timeout(10_000) })
    } catch (error) {
      const unreachable = error instanceof TypeError || (error instanceof DOMException && error.name === 'TimeoutError') ||
        (error instanceof ApiError && ([502, 504].includes(error.status) || (error.status === 500 && error.empty)))
      if (this.mode !== 'auto' || !unreachable) throw error
      // Choose the offline dataset before selecting docs; never substitute fake answers for real docs.
      this.isDemo = true
      response = await this.request('/api/docs')
    }
    const data = await response.json() as { sources: { docs: Document[] }[] }
    return data.sources.flatMap((source) => source.docs)
  }

  async createChat(docIds: string[], title: string): Promise<string> {
    const response = await this.request('/api/chats', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ doc_ids: docIds, title }),
    })
    const chat = await response.json() as { id: string }
    return chat.id
  }

  async getChanges(signal?: AbortSignal): Promise<ChangeEntry[]> {
    if (this.isDemo) return []
    const response = await this.request('/api/changes', { signal })
    return ((await response.json()) as { changes: ChangeEntry[] }).changes
  }

  async getComparison(id: string, signal?: AbortSignal): Promise<Comparison> {
    const response = await this.request(`/api/changes/${encodeURIComponent(id)}`, { signal })
    const data = await response.json() as Comparison
    if (!data.image || !data.v1 || !data.v2 || !Array.isArray(data.changes)) throw new Error('Comparison images are not available for this change.')
    return data
  }

  async getDocument(docId: string): Promise<Document> {
    const response = await this.request(`/api/docs/${encodeURIComponent(docId)}`)
    return response.json() as Promise<Document>
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

  async askQuestion(chatId: string, content: string, docIds: string[], callbacks: StreamCallbacks): Promise<Answer> {
    const response = await this.request(`/api/chats/${encodeURIComponent(chatId)}/messages`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({ content, doc_ids: docIds }),
    })
    return readAnswerStream(response, callbacks)
  }
}

const setting = import.meta.env.VITE_USE_MOCK
export const workspaceApi = new WorkspaceApi(setting === 'true' ? 'demo' : setting === 'false' ? 'real' : 'auto')
