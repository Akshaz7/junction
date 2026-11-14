import type { Answer, Document } from './types'

// Temporary switch until S-03. Explicitly set false to use the backend.
export const useMock = import.meta.env.VITE_USE_MOCK !== 'false'

async function request(path: string, init?: RequestInit): Promise<Response> {
  if (useMock) {
    const { handleMockRequest } = await import('../mock/handler')
    const response = await handleMockRequest(new Request(new URL(path, window.location.origin), init))
    if (response) return response
  }
  const response = await fetch(path, init)
  if (!response.ok) throw new Error(`Request failed (${response.status}). Please try again.`)
  return response
}

export async function getDocuments(): Promise<Document[]> {
  const response = await request('/api/docs')
  return response.json()
}

export async function askQuestion(question: string, docIds: string[], onStatus: (detail: string) => void): Promise<Answer> {
  const response = await request('/api/chats/demo/messages', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, doc_ids: docIds }),
  })
  if (!response.ok || !response.body) throw new Error('The answer stream could not be opened.')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let answer: Answer | undefined
  try {
    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, '\n')
      let boundary: number
      while ((boundary = buffer.indexOf('\n\n')) !== -1) {
        const block = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        const event = block.split('\n').find((line) => line.startsWith('event:'))?.slice(6).trim()
        const data = block.split('\n').filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trimStart()).join('\n')
        if (!data) continue
        if (event === 'answer') answer = JSON.parse(data) as Answer
        if (event === 'status') {
          const status = JSON.parse(data) as { detail?: string }
          if (status.detail) onStatus(status.detail)
        }
      }
      if (done) break
    }
  } finally {
    reader.releaseLock()
  }
  if (!answer) throw new Error('The response ended before an answer arrived.')
  return answer
}
