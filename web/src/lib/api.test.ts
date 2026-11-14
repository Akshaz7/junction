import { describe, expect, it, vi } from 'vitest'
import { readAnswerStream, WorkspaceApi } from './api'
import { demoDocument, makeDemoAnswer } from '../mock/handler'

const callbacks = () => ({ onStatus: vi.fn(), onTrace: vi.fn() })
const documentResponse = () => Response.json({ total: 1, sources: [{ source: 'demo', count: 1, docs: [demoDocument] }] })
const answer = makeDemoAnswer('How many windows are there?')
const event = (type: string, payload: unknown) => `event: ${type}\r\ndata: ${JSON.stringify(payload)}\r\n\r\n`

function chunkedStream(text: string) {
  const bytes = new TextEncoder().encode(text)
  return new Response(new ReadableStream({
    start(controller) {
      // One byte per chunk exercises split UTF-8, CRLF delimiters and JSON tokens.
      for (const byte of bytes) controller.enqueue(Uint8Array.of(byte))
      controller.close()
    },
  }))
}

describe('backend chat contract', () => {
  it('loads a saved chat through the workspace transport and reports real failures', async () => {
    const saved = { id: 'saved/chat', doc_id: demoDocument.doc_id, messages: [] }
    const transport = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(saved))
      .mockResolvedValueOnce(Response.json({ detail: 'chat not found' }, { status: 404 }))
    const api = new WorkspaceApi('real', transport)
    const signal = new AbortController().signal
    expect(await api.getChat(saved.id, signal)).toEqual(saved)
    expect(transport).toHaveBeenCalledWith('/api/chats/saved%2Fchat', { signal })
    await expect(api.getChat('missing')).rejects.toThrow('chat not found')
    expect(api.isDemo).toBe(false)
  })

  it('flattens grouped docs, creates a real chat and sends content with selected doc_ids', async () => {
    const transport = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(documentResponse())
      .mockResolvedValueOnce(Response.json({ id: 'persisted-chat' }))
      .mockResolvedValueOnce(chunkedStream(event('answer', answer)))
    const api = new WorkspaceApi('real', transport)
    expect(await api.getDocuments()).toEqual([demoDocument])
    const ids = [demoDocument.doc_id]
    const id = await api.createChat(ids, 'Windows')
    expect(id).toBe('persisted-chat')
    expect(await api.askQuestion(id, answer.question, ids, callbacks())).toEqual(answer)
    expect(transport.mock.calls[1][0]).toBe('/api/chats')
    expect(JSON.parse(transport.mock.calls[1][1]!.body as string)).toEqual({ doc_ids: ids, title: 'Windows' })
    expect(transport.mock.calls[2][0]).toBe('/api/chats/persisted-chat/messages')
    expect(JSON.parse(transport.mock.calls[2][1]!.body as string)).toEqual({ content: answer.question, doc_ids: ids })
    expect(api.isDemo).toBe(false)
  })

  it('uses the labeled offline fixture when the backend cannot be reached', async () => {
    const transport = vi.fn<typeof fetch>().mockRejectedValue(new TypeError('Failed to fetch'))
    const api = new WorkspaceApi('auto', transport)
    expect(await api.getDocuments()).toEqual([demoDocument])
    expect(api.isDemo).toBe(true)
    const id = await api.createChat([demoDocument.doc_id], 'Windows')
    const result = await api.askQuestion(id, answer.question, [demoDocument.doc_id], callbacks())
    expect(result.answer.text_md).toContain('generated for demo')
    expect(transport).toHaveBeenCalledTimes(1)
  })

  it('handles an unreachable Vite proxy but preserves real API and database errors', async () => {
    const offline = new WorkspaceApi('auto', vi.fn<typeof fetch>().mockResolvedValue(new Response('', { status: 500 })))
    expect(await offline.getDocuments()).toEqual([demoDocument])
    const unavailable = new WorkspaceApi('auto', vi.fn<typeof fetch>().mockImplementation(async () => Response.json({ detail: 'Database unavailable' }, { status: 503 })))
    await expect(unavailable.getDocuments()).rejects.toThrow('Database unavailable')
    expect(unavailable.isDemo).toBe(false)
    const real = new WorkspaceApi('real', vi.fn<typeof fetch>().mockRejectedValue(new TypeError('Failed to fetch')))
    await expect(real.getDocuments()).rejects.toThrow('Failed to fetch')
    expect(real.isDemo).toBe(false)
  })

  it('does not replace a failed real answer with fabricated fixture content', async () => {
    const api = new WorkspaceApi('auto', vi.fn<typeof fetch>().mockRejectedValue(new TypeError('Disconnected')))
    await expect(api.askQuestion('real-chat', answer.question, ['real-doc'], callbacks())).rejects.toThrow('Disconnected')
    expect(api.isDemo).toBe(false)
  })
})

describe('server-sent answer events', () => {
  it('decodes split events and streams status.text and trace before the answer', async () => {
    const handlers = callbacks()
    const text = ': heartbeat\r\n\r\n' + event('status', { text: 'Thinking…' }) +
      event('trace', answer.trace[0]) + event('answer', answer)
    expect(await readAnswerStream(chunkedStream(text), handlers)).toEqual(answer)
    expect(handlers.onStatus).toHaveBeenCalledWith('Thinking…')
    expect(handlers.onTrace).toHaveBeenCalledWith(answer.trace[0])
    expect(handlers.onStatus.mock.invocationCallOrder[0]).toBeLessThan(handlers.onTrace.mock.invocationCallOrder[0])
  })

  it('reports stream errors and truncated responses instead of hanging', async () => {
    await expect(readAnswerStream(chunkedStream(event('error', { detail: 'Engine unavailable' })), callbacks())).rejects.toThrow('Engine unavailable')
    await expect(readAnswerStream(chunkedStream(event('status', { text: 'Thinking…' })), callbacks())).rejects.toThrow('before an answer arrived')
  })
})
