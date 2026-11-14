import { describe, expect, it } from 'vitest'
import { chatLink, savedExchanges } from './chat-history'
import { makeDemoAnswer } from '../mock/handler'

describe('saved chat links', () => {
  it('decodes chat IDs and question text without interpreting other routes', () => {
    expect(chatLink('#/chat/saved%2Fchat')).toEqual({ kind: 'chat', id: 'saved/chat' })
    expect(chatLink('#/chat/%ZZ')).toBeNull()
    expect(chatLink('#/chat?chat=saved%2Fchat')).toEqual({ kind: 'chat', id: 'saved/chat' })
    expect(chatLink('#/chat?question=Where%20is%20A%2BB%3F')).toEqual({ kind: 'question', question: 'Where is A+B?' })
    expect(chatLink('#/overview?chat=saved')).toBeNull()
    expect(chatLink('#/chat')).toBeNull()
  })

  it('keeps complete answers, plain replies, and unanswered questions in order', () => {
    const answer = makeDemoAnswer('How many windows are there?')
    expect(savedExchanges({ id: 'saved', doc_id: null, messages: [
      { id: '1', role: 'user', content: answer.question, answer: null },
      { id: '2', role: 'assistant', content: answer.answer.text_md, answer },
      { id: '3', role: 'user', content: 'What about doors?', answer: null },
      { id: '4', role: 'assistant', content: 'No door data in this drawing.', answer: null },
      { id: '5', role: 'user', content: 'And stairs?', answer: null },
    ] })).toEqual([
      { id: '1', question: answer.question, answer, content: answer.answer.text_md },
      { id: '3', question: 'What about doors?', answer: null, content: 'No door data in this drawing.' },
      { id: '5', question: 'And stairs?', answer: null, content: '' },
    ])
  })
})
