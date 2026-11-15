import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { OverviewApi, isJunkName, realFindings, chatHref, chatPreview, findingCounts, latestChats, oneLine, overviewStarters, starterHref, topFindings, weeklyChanges, cleanTitle, groupFindings, visibleChats, ruleName, type OverviewChat, type OverviewFinding } from './overview'
import type { Answer, ChangeEntry } from './types'

const chat = (id: string, created_at: string): OverviewChat => ({ id, title: 'A question', created_at })
const change = (id: string, created_at: string): ChangeEntry => ({ id, created_at, type: 'new_version', doc_a: 'a', doc_b: `doc-${id}`, summary: {} })
const finding = (id: string, severity: OverviewFinding['severity']): OverviewFinding => ({ id, severity, doc_id: 'doc', message: 'Check this item.', created_at: '2026-11-14T10:00:00Z' })
const transport = (responses: Record<string, [number, unknown]>, paths: string[] = []): typeof fetch => async (input) => {
  const path = String(input)
  paths.push(path)
  if (!responses[path]) throw new Error(`Unexpected request ${path}`)
  const [status, body] = responses[path]
  return Response.json(body, { status })
}

describe('overview data', () => {
  it('shows only this calendar week, newest first, capped at five without mutating the feed', () => {
    const now = new Date(2026, 10, 14, 12)
    const rows = [change('old', new Date(2026, 10, 8, 23).toISOString()), ...Array.from({ length: 7 }, (_, i) => change(String(i), new Date(2026, 10, 9 + i, 10).toISOString())), change('invalid', 'bad')]
    expect(weeklyChanges(rows, now).map((row) => row.id)).toEqual(['5', '4', '3', '2', '1'])
    expect(rows[0].id).toBe('old')
    expect(weeklyChanges(rows, new Date(2026, 10, 16))).toEqual([])
  })

  it('counts every finding while showing the three most severe first', () => {
    const rows = [finding('i', 'info'), finding('s', 'suggestion'), finding('v', 'violation'), finding('v2', 'violation')]
    expect(findingCounts(rows)).toEqual({ violation: 2, suggestion: 1, info: 1 })
    expect(topFindings(rows).map((row) => row.id)).toEqual(['v', 'v2', 's'])
  })

  it('does not pair an old answer or cost with a new unanswered question', () => {
    const row: OverviewChat = { ...chat('1', ''), messages: [
      { id: 'a', role: 'assistant', content: 'Old answer', created_at: '', answer: null },
      { id: 'q', role: 'user', content: 'Latest question', created_at: '', answer: null },
    ] }
    expect(chatPreview(row)).toEqual({ question: 'Latest question', answer: 'No answer yet.', cost: undefined })
    row.messages!.push({ id: 'b', role: 'assistant', content: 'Fallback', created_at: '', answer: { answer: { text_md: '**Two** windows. [1]' }, cost: { usd_total: 0 } } as Answer })
    expect(chatPreview(row)).toEqual({ question: 'Latest question', answer: 'Two windows. [1]', cost: 0 })
    expect(chatPreview({ ...row, detailUnavailable: true }).answer).toBe('Answer unavailable.')
  })

  it('keeps the newest five chats and encodes route values', () => {
    const rows = Array.from({ length: 7 }, (_, i) => chat(String(i), `2026-11-${10 + i}T10:00:00Z`))
    expect(latestChats(rows).map((row) => row.id)).toEqual(['6', '5', '4', '3', '2'])
    expect(chatHref('a&b')).toBe('#/chat?chat=a%26b')
    expect(starterHref('Where? & why')).toBe('#/chat?question=Where%3F%20%26%20why')
    expect(oneLine('**Area** of [room](https://example.com)\n is `12 m2`.')).toBe('Area of room is 12 m2.')
  })

  it('matches all four private chat starter questions', () => {
    const source = readFileSync(new URL('../components/chat-screen.tsx', import.meta.url), 'utf8')
    for (const starter of overviewStarters) expect(source).toContain(`question: '${starter.question}'`)
    expect(overviewStarters).toHaveLength(4)
  })
})

describe('overview real API', () => {
  it('treats findings and bench 404s as missing and keeps service errors visible', async () => {
    const api = new OverviewApi(transport({ '/api/findings': [404, {}], '/api/bench/latest': [404, {}], '/api/changes': [503, {}], '/api/chats': [503, {}] }))
    expect(await api.getFindings()).toEqual([])
    expect(await api.getBench()).toBeNull()
    await expect(api.getChanges()).rejects.toThrow('(503)')
    await expect(api.getChats()).rejects.toThrow('(503)')
    await expect(new OverviewApi(transport({ '/api/findings': [500, {}] })).getFindings()).rejects.toThrow('(500)')
  })

  it('loads messages for at most ten chats (the page then shows five with answers) and preserves an unavailable detail', async () => {
    const paths: string[] = []
    const chats = Array.from({ length: 12 }, (_, i) => chat(String(i).padStart(2,'0'), `2026-11-${10 + i}T10:00:00Z`))
    const responses: Record<string, [number, unknown]> = { '/api/chats': [200, { chats }] }
    for (const row of chats) responses[`/api/chats/${row.id}`] = [200, { ...row, messages: [] }]
    responses['/api/chats/03'] = [404, {}]
    const rows = await new OverviewApi(transport(responses, paths)).getChats()
    expect(rows.map((row) => row.id)).toHaveLength(10)
    expect(rows.find((row) => row.id === '03')?.detailUnavailable).toBe(true)
    expect(paths).toHaveLength(11)
    expect(paths).not.toContain('/api/chats/00')
  })

  it('uses the supplied abort signal and never substitutes data on network failure', async () => {
    const controller = new AbortController()
    const api = new OverviewApi(async (_input, init) => {
      expect(init?.signal).toBe(controller.signal)
      throw new TypeError('offline')
    })
    await expect(api.getChanges(controller.signal)).rejects.toThrow('offline')
  })
})

describe('overview plain-language helpers', () => {
  it('cleans file-style titles and hides test uploads and repeats', () => {
    expect(cleanTitle('uploads__Ground-floor-plan_p001.pdf')).toBe('Uploads  Ground floor plan'.replace('Uploads  ', ''))
    expect(cleanTitle('web3-notes-1794666920790-generated-for-demo')).toBe('Web3 notes')
    const now = new Date(2026, 10, 14, 12), at = new Date(2026, 10, 14, 10).toISOString()
    const rows: ChangeEntry[] = ['qa-1', 'smoke-x', 'audit-2', 'w65-3', 'web3-4', 'Real plan', 'Real plan'].map((name, i) => ({ id: String(i), created_at: at, type: 'new_document', doc_a: null, doc_b: name, summary: { doc_id: name, title: name } }))
    expect(weeklyChanges(rows, now).map((row) => row.summary.title)).toEqual(['Real plan'])
  })

  it('groups identical findings into one card listing the storeys, with a short rule name', () => {
    const base = { doc_id: 'ac20', severity: 'suggestion' as const, message: 'long', created_at: '2026-11-14T10:00:00Z', rule: { source_title: 'Decree of the Ministry of the Environment on fire safety of buildings 848/2017 (English text), 33 §' } }
    const rows: OverviewFinding[] = ['Keller', 'EG', '2. OG'].map((storey, i) => ({ ...base, id: String(i), detail: { title: `Only 1 exit found on ${storey}`, storey } }))
    const groups = groupFindings(rows)
    expect(groups).toHaveLength(1)
    expect(groups[0].storeys).toEqual(['Keller', 'EG', '2. OG'])
    expect(ruleName(rows[0])).toBe('Fire safety 848/2017 §33')
  })

  it('drops chats with no answer and repeated questions', () => {
    const answered = (id: string, q: string): OverviewChat => ({ id, title: null, created_at: '2026-11-14T10:00:00Z', messages: [{ id: 'u', role: 'user', content: q, created_at: '', answer: null }, { id: 'a', role: 'assistant', content: 'Done.', created_at: '', answer: null }] })
    const empty: OverviewChat = { id: 'e', title: 'x', created_at: '2026-11-14T10:00:00Z', messages: [{ id: 'u', role: 'user', content: 'Hi', created_at: '', answer: null }] }
    expect(visibleChats([empty, answered('1', 'How many doors?'), answered('2', 'how many doors?')]).map((c) => c.id)).toEqual(['1'])
  })
})

describe('overview junk filtering', () => {
  it('flags stress, corrupt and untitled uploads as test uploads', async () => {
    const { isTestUpload } = await import('./overview')
    expect(isTestUpload('Stress 3 big plan.pdf')).toBe(true)
    expect(isTestUpload('uploads__corrupt-file.pdf')).toBe(true)
    expect(isTestUpload('uploads__1234567890123.png')).toBe(true)
    expect(isTestUpload('Villa ground floor.pdf')).toBe(false)
  })
  it('drops timed-out answers from the latest list', async () => {
    const { hasAnswer } = await import('./overview')
    const chat = (content: string) => ({ id: 'c', title: null, created_at: '2026-11-14T10:00:00Z', messages: [
      { id: 'm1', role: 'user', content: 'q', created_at: '', answer: null }, { id: 'm2', role: 'assistant', content, created_at: '', answer: null }] })
    expect(hasAnswer(chat('This took longer than 40 s, so I stopped. Nothing was guessed.'))).toBe(false)
    expect(hasAnswer(chat('There are 11 doors.'))).toBe(true)
  })
})

describe('test-junk filtering on the overview', () => {
  it('matches the library junk pattern by title and by id tail', () => {
    for (const name of ['judge-features-duplex', 'Judge multi duplex', 'break-ui-x', 'lead-check', 'smoke-a', 'stress_b', 'ext__judge-features-duplex.ifc'])
      expect(isJunkName(name)).toBe(true)
    for (const name of ['Duplex A', 'Schependomlaan design', '', null]) expect(isJunkName(name)).toBe(false)
  })
  it('drops findings of junk documents and keeps real ones', () => {
    const f = (doc_id: string) => ({ id: doc_id, doc_id, severity: 'info', message: 'm', created_at: '2026-11-15T00:00:00Z' }) as OverviewFinding
    const kept = realFindings([f('ifc__duplex-a'), f('uploads__judge-features-duplex'), f('x__plan')], (id) => id === 'x__plan' ? 'Break test plan' : id)
    expect(kept.map((x) => x.doc_id)).toEqual(['ifc__duplex-a'])
  })
})
