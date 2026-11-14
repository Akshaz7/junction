import type { Answer, ChangeEntry } from './types'
import type { BenchResult } from './dashboard'

// chat-screen.tsx keeps its starters private. Keep these four questions in sync.
export const overviewStarters = [
  { title: 'Count on a plan', question: 'How many windows are there?' },
  { title: 'Find a room’s area', question: 'What is the area of this room?' },
  { title: 'Locate something', question: 'Where is the stair core on level 2?' },
  { title: 'Read a drawing', question: 'What does this drawing say about the doors?' },
] as const

export interface OverviewFinding {
  id: string
  doc_id: string
  severity: 'info' | 'suggestion' | 'violation'
  message: string
  created_at: string
  rule?: { source_title?: string; quote?: string; url?: string }
}

export interface OverviewChat {
  id: string
  title: string | null
  created_at: string
  messages?: {
    id: string; role: string; content: string; created_at: string; answer: Answer | null
  }[]
  detailUnavailable?: boolean
}

function timestamp(value: string) { return Date.parse(value) || 0 }

export function latestChats(chats: OverviewChat[]) {
  return [...chats].sort((a, b) => timestamp(b.created_at) - timestamp(a.created_at)).slice(0, 5)
}

/** Calendar week starts on Monday in the user's local timezone. */
export function weeklyChanges(changes: ChangeEntry[], now = new Date()) {
  const start = new Date(now)
  start.setHours(0, 0, 0, 0)
  start.setDate(start.getDate() - (start.getDay() + 6) % 7)
  return changes.filter((change) => timestamp(change.created_at) >= start.getTime() && timestamp(change.created_at) <= now.getTime())
    .sort((a, b) => timestamp(b.created_at) - timestamp(a.created_at)).slice(0, 5)
}

export function findingCounts(findings: OverviewFinding[]) {
  return Object.fromEntries(['violation', 'suggestion', 'info'].map((severity) => [severity, findings.filter((finding) => finding.severity === severity).length]))
}

export function topFindings(findings: OverviewFinding[]) {
  const priority = { violation: 0, suggestion: 1, info: 2 }
  return [...findings].sort((a, b) => priority[a.severity] - priority[b.severity] || timestamp(b.created_at) - timestamp(a.created_at)).slice(0, 3)
}

export function oneLine(markdown: string) {
  return markdown.replace(/\[([^\]]+)\]\([^)]*\)/g, '$1').replace(/[*_`#>]/g, '').replace(/\s+/g, ' ').trim()
}

export function chatPreview(chat: OverviewChat) {
  const messages = chat.messages || []
  const questionIndex = messages.map((message) => message.role).lastIndexOf('user')
  const response = messages.slice(questionIndex + 1).reverse().find((message) => message.role === 'assistant')
  return {
    question: questionIndex >= 0 ? messages[questionIndex].content : chat.title || 'Untitled chat',
    answer: chat.detailUnavailable ? 'Answer unavailable.' : response ? oneLine(response.answer?.answer.text_md || response.content) : 'No answer yet.',
    cost: response?.answer?.cost.usd_total,
  }
}

export const chatHref = (id: string) => `#/chat?chat=${encodeURIComponent(id)}`
export const starterHref = (question: string) => `#/chat?question=${encodeURIComponent(question)}`

export function overviewDate(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? 'Date unavailable' : date.toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

/** Real reads only: missing data stays missing, independent of the offline chat demo. */
export class OverviewApi {
  constructor(private transport: typeof fetch = (...args) => fetch(...args)) {}

  private async read<T>(path: string, signal?: AbortSignal, missing?: T): Promise<T> {
    const response = await this.transport(path, { signal })
    if (response.status === 404 && missing !== undefined) return missing
    if (!response.ok) throw new Error(`Could not load this section (${response.status}).`)
    return response.json() as Promise<T>
  }

  async getChanges(signal?: AbortSignal) {
    return (await this.read<{ changes: ChangeEntry[] }>('/api/changes', signal)).changes
  }

  async getFindings(signal?: AbortSignal) {
    return (await this.read<{ findings: OverviewFinding[] }>('/api/findings', signal, { findings: [] })).findings
  }

  getBench(signal?: AbortSignal) {
    return this.read<BenchResult | null>('/api/bench/latest', signal, null)
  }

  async getChats(signal?: AbortSignal) {
    const { chats } = await this.read<{ chats: OverviewChat[] }>('/api/chats', signal)
    // The list contains metadata only; message bodies and answer costs live in detail.
    return Promise.all(latestChats(chats).map(async (chat) => {
      try { return await this.read<OverviewChat>(`/api/chats/${encodeURIComponent(chat.id)}`, signal) }
      catch (error) {
        if (signal?.aborted) throw error
        return { ...chat, detailUnavailable: true }
      }
    }))
  }
}

export const overviewApi = new OverviewApi()
