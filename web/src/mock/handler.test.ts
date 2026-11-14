import { describe, expect, it } from 'vitest'
import { demoDocument, handleMockRequest } from './handler'
import type { Answer } from '../lib/types'

describe('temporary contract endpoints', () => {
  it('lists explicitly generated sample documents', async () => {
    const response = await handleMockRequest(new Request('http://localhost/api/docs'))
    const docs = await response!.json()
    expect(docs.sources[0].docs).toEqual([demoDocument])
    expect(docs.sources[0].docs[0].title).toContain('generated for demo')
  })

  it('streams an answer with matching citation, box and scene item IDs', async () => {
    const response = await handleMockRequest(new Request('http://localhost/api/chats/demo/messages', {
      method: 'POST', body: JSON.stringify({ content: 'How many windows are in the sample plan?', doc_ids: [demoDocument.doc_id] }),
    }))
    expect(response!.headers.get('content-type')).toBe('text/event-stream')
    const stream = await response!.text()
    expect(stream).toContain('event: status\n')
    expect(stream).toContain('event: trace\n')
    const answerEvent = stream.split('\n\n').find((event) => event.startsWith('event: answer'))!
    const answer = JSON.parse(answerEvent.split('\ndata: ')[1]) as Answer
    const ids = answer.evidence.boxes.map((box) => box.item_id)
    expect(answer.answer.value).toBe(ids.length)
    expect(answer.citations[0].item_ids).toEqual(ids)
    expect(answer.evidence.scene.highlight_item_ids).toEqual(ids)
    expect(answer.evidence.boxes.map((box) => box.label)).toEqual(['1', '2'])
  })

  it('abstains on unsupported questions and documents, and leaves other endpoints alone', async () => {
    for (const body of [
      { content: 'What is the floor area?' },
      { content: 'How many windows?', doc_ids: ['unknown__drawing'] },
    ]) {
      const response = await handleMockRequest(new Request('http://localhost/api/chats/demo/messages', { method: 'POST', body: JSON.stringify(body) }))
      expect(await response!.text()).toContain('"abstained":true')
    }
    expect(await handleMockRequest(new Request('http://localhost/api/bench/latest'))).toBeNull()
  })
})
