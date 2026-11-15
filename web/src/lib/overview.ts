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
  detail?: { title?: string; storey?: string; source?: { title?: string } }
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

export function latestChats(chats: OverviewChat[], limit = 5) {
  return [...chats].sort((a, b) => timestamp(b.created_at) - timestamp(a.created_at)).slice(0, limit)
}

/** Calendar week starts on Monday in the user's local timezone. */
const testUpload = /^(smoke|qa|audit|w\d+|web\d*)[-_]|^stress|corrupt/i

/** A readable title from a file-style name: no extension, sheet codes, timestamps or "generated for demo" suffix. */
export function cleanTitle(raw: string) {
  const name = raw.replace(/^uploads__/, '').replace(/\.(pdf|png|jpe?g|dxf|ifc|dwg|webp)$/i, '')
    .replace(/[-_ ]generated[-_ ]for[-_ ]demo.*$/i, '').replace(/[-_ ]?\d{10,}/g, '').replace(/[-_ ]?p\d{3}$/i, '')
    .replace(/^[a-z]{2}[-_][a-z]+[-_][a-z]+-dfe[-_a-z0-9]*$/i, '')
  const words = name.replace(/[-_]+/g, ' ').replace(/\s+/g, ' ').trim()
  // Keep sheet codes readable: "M 101A piping plan" -> "M-101A piping plan", "A 2 dorm" -> "A-2 dorm".
  const coded = words.replace(/^([A-Z]{1,2}) (\d{1,4}[A-Z]?)\b/, '$1-$2')
  return coded ? coded.charAt(0).toUpperCase() + coded.slice(1) : 'Untitled drawing'
}

/** Mirrors JUNK_TITLE in engine/library.py: overnight test traffic is hidden everywhere. */
const junkTitle = /^(?:smoke[-_ ]|stress[-_ ]|qa[-_]|web3[-_]notes[-_]|generated[ _-]+for[ _-]+demo|judge[-_ ]|break[-_ ]|lead[-_ ])/i
export function isJunkName(raw: string | null | undefined) {
  const name = String(raw || '').replace(/^uploads__/, '')
  return junkTitle.test(name) || junkTitle.test(name.split('__').slice(-1)[0]) || /upload-fixture|generated[ _-]+for[ _-]+demo|cross-device/i.test(name)
}

/** Findings whose document is not test junk (checked by id and by the library title). */
export function realFindings(findings: OverviewFinding[], titleOf: (id: string) => string = (id) => id) {
  return findings.filter((finding) => !isJunkName(finding.doc_id) && !isJunkName(titleOf(finding.doc_id)))
}

export function isTestUpload(raw: string) {
  const name = raw.replace(/^uploads__/, '')
  return testUpload.test(name) || /^screenshot/i.test(name) || cleanTitle(name) === 'Untitled drawing'
}

/** This week's changes, test uploads and repeats of the same file removed. */
export function weeklyChanges(changes: ChangeEntry[], now = new Date()) {
  const start = new Date(now)
  start.setHours(0, 0, 0, 0)
  start.setDate(start.getDate() - (start.getDay() + 6) % 7)
  const seen = new Set<string>()
  return changes.filter((change) => timestamp(change.created_at) >= start.getTime() && timestamp(change.created_at) <= now.getTime())
    .filter((change) => !isTestUpload(String(change.summary.doc_id || change.doc_b || change.summary.title || '')))
    .sort((a, b) => timestamp(b.created_at) - timestamp(a.created_at))
    .filter((change) => {
      const key = `${change.type}:${cleanTitle(String(change.summary.title || change.summary.doc_id || change.doc_b || ''))}`
      if (seen.has(key)) return false
      seen.add(key); return true
    }).slice(0, 5)
}

export function changeSubtitle(change: ChangeEntry) {
  const time = new Date(change.created_at)
  const at = Number.isNaN(time.getTime()) ? '' : ` · ${time.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}`
  return `${change.type === 'new_version' ? 'New version' : 'New upload'}${at}`
}

const decrees: Record<string, string> = { '848/2017': 'Fire safety', '241/2017': 'Accessibility', '1007/2017': 'Safety in use', '1008/2017': 'Residential design' }
/** "Fire safety 848/2017 §33" from the long decree title. */
export function ruleName(finding: OverviewFinding) {
  const title = finding.rule?.source_title || ''
  const decree = title.match(/\b(\d{3,4}\/\d{4})\b/)?.[1]
  const section = `${title} ${finding.detail?.source?.title || ''}`.match(/(\d+)\s*§/)?.[1]
  if (!decree) return title.split(/[,(]/)[0].trim()
  return `${decrees[decree] || 'Rule'} ${decree}${section ? ` §${section}` : ''}`
}

export interface FindingGroup { key: string; severity: OverviewFinding['severity']; line: string; rule: string; storeys: string[]; doc_id: string; finding: OverviewFinding; count: number }

/** One card per rule and severity; storeys listed instead of repeating the card. */
export function groupFindings(findings: OverviewFinding[]): FindingGroup[] {
  const priority = { violation: 0, suggestion: 1, info: 2 }
  const groups = new Map<string, FindingGroup>()
  for (const finding of [...findings].sort((a, b) => priority[a.severity] - priority[b.severity] || timestamp(b.created_at) - timestamp(a.created_at))) {
    const rule = ruleName(finding)
    const key = `${finding.doc_id}|${finding.severity}|${rule}|${(finding.detail?.title || finding.message).replace(/\s+on\s+.*$/, '')}`
    const storey = finding.detail?.storey
    const existing = groups.get(key)
    if (existing) { existing.count++; if (storey && !existing.storeys.includes(storey)) existing.storeys.push(storey); continue }
    groups.set(key, { key, severity: finding.severity, line: finding.detail?.title || finding.message, rule, storeys: storey ? [storey] : [], doc_id: finding.doc_id, finding, count: 1 })
  }
  return [...groups.values()]
}

export const severityLabel = (severity: OverviewFinding['severity']) => ({ violation: 'Violation', suggestion: 'Worth checking', info: 'Note' })[severity]

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
    question: oneLine(questionIndex >= 0 ? messages[questionIndex].content : chat.title || 'Untitled chat'),
    answer: chat.detailUnavailable ? 'Answer unavailable.' : response ? oneLine(response.answer?.answer.text_md || response.content) : 'No answer yet.',
    cost: response?.answer?.cost.usd_total,
  }
}

const failedAnswer = /took longer than \d+ ?s|could not tell which|nothing was guessed|answer unavailable/i

export function hasAnswer(chat: OverviewChat) {
  if (chat.detailUnavailable || chatPreview(chat).answer === 'No answer yet.') return false
  const messages = chat.messages || []
  const response = [...messages].reverse().find((message) => message.role === 'assistant')
  if (response?.answer?.answer.abstained) return false
  return !failedAnswer.test(chatPreview(chat).answer)
}

/** Chats that have an answer, with repeats of the same question dropped. */
export function visibleChats(chats: OverviewChat[], limit = 5) {
  const seen = new Set<string>()
  return chats.filter((chat) => !isJunkName(chat.title) && !isJunkName(chatPreview(chat).question)).filter(hasAnswer).filter((chat) => {
    const key = chatPreview(chat).question.trim().toLowerCase()
    if (seen.has(key)) return false
    seen.add(key); return true
  }).slice(0, limit)
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
    return Promise.all(latestChats(chats, 10).map(async (chat) => {
      try { return await this.read<OverviewChat>(`/api/chats/${encodeURIComponent(chat.id)}`, signal) }
      catch (error) {
        if (signal?.aborted) throw error
        return { ...chat, detailUnavailable: true }
      }
    }))
  }
}

export const overviewApi = new OverviewApi()
