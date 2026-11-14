import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { OverviewApi, chatHref, chatPreview, findingCounts, latestChats, oneLine, overviewStarters, starterHref, topFindings, weeklyChanges, type OverviewChat, type OverviewFinding } from './overview'
import type { Answer, ChangeEntry } from './types'

const chat = (id: string, created_at: string): OverviewChat => ({ id, title: 'A question', created_at })
const change = (id: string, created_at: string): ChangeEntry => ({ id, created_at, type: 'new_version', doc_a: 'a', doc_b: 'b', summary: {} })
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

  it('loads messages for at most five chats and preserves an unavailable detail', async () => {
    const paths: string[] = []
    const chats = Array.from({ length: 6 }, (_, i) => chat(String(i), `2026-11-${10 + i}T10:00:00Z`))
    const responses: Record<string, [number, unknown]> = { '/api/chats': [200, { chats }] }
    for (const row of chats) responses[`/api/chats/${row.id}`] = [200, { ...row, messages: [] }]
    responses['/api/chats/3'] = [404, {}]
    const rows = await new OverviewApi(transport(responses, paths)).getChats()
    expect(rows.map((row) => row.id)).toEqual(['5', '4', '3', '2', '1'])
    expect(rows[2].detailUnavailable).toBe(true)
    expect(paths).toHaveLength(6)
    expect(paths).not.toContain('/api/chats/0')
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
