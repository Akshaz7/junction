import type { Answer, SavedChat } from './types'

export interface ChatExchange { id: string; question: string; answer: Answer | null; content: string }

export function chatLink(hash: string) {
  const [route, query] = hash.replace(/^#\/?/, '').split('?')
  const params = new URLSearchParams(query)
  if (route !== 'chat') return null
  const id = params.get('chat')
  if (id) return { kind: 'chat' as const, id }
  const question = params.get('question')
  return question === null ? null : { kind: 'question' as const, question }
}

/** Preserve saved message order, including plain text and unanswered questions. */
export function savedExchanges(chat: SavedChat): ChatExchange[] {
  const exchanges: ChatExchange[] = []
  for (const message of chat.messages) {
    if (message.role === 'user') {
      exchanges.push({ id: message.id, question: message.content, answer: null, content: '' })
    } else if (message.role === 'assistant') {
      const previous = exchanges.at(-1)
      const reply = { answer: message.answer, content: message.content }
      if (previous && !previous.answer && !previous.content) Object.assign(previous, reply)
      else exchanges.push({ id: message.id, question: message.answer?.question ?? '', ...reply })
    }
  }
  return exchanges
}
