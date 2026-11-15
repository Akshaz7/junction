// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { demoDocument, makeDemoAnswer } from '../mock/handler'
import type { Answer } from '../lib/types'

const api = vi.hoisted(() => ({ getChat: vi.fn() }))
const live = vi.hoisted(() => ({ listeners: new Set<(event: unknown) => void>() }))
vi.mock('../lib/api', () => ({ workspaceApi: api }))
vi.mock('../lib/chat-live', () => ({ chatLive: { subscribe: (fn: (event: unknown) => void) => { live.listeners.add(fn); return () => live.listeners.delete(fn) } } }))
vi.mock('../lib/use-scene-edits', () => ({ useSceneEdits: () => ({}) }))
vi.mock('./document-viewer', () => ({
  useViewerSheet: () => false,
  DocumentViewer: ({ answer }: { answer: Answer }) => <aside data-testid="open-drawing">{answer.answer_id}</aside>,
}))
import { ChatScreen } from './chat-screen'

let host: HTMLDivElement, root: Root
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  window.history.replaceState(null, '', '#/chat?chat=cost-regression')
  const values = new Map<string, string>()
  Object.defineProperty(window, 'localStorage', { configurable: true, value: { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => values.set(key, value) } })
  live.listeners.clear()
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
})
afterEach(async () => { await act(async () => root.unmount()); host.remove() })

it('keeps each answer’s real cost when a drawing opens and a saved chat refreshes', async () => {
  const paid = makeDemoAnswer('How many windows are there?')
  paid.answer_id = 'paid-answer'
  paid.cost = { usd_total: 0.005434, calls: [{ model: 'test-model', cost_usd: 0.005434 }] }
  const cached = { ...paid, answer_id: 'cached-answer', cost: { usd_total: 0, calls: [{ model: 'test-model', cost_usd: 0, cache_hit: true }] } }
  const snapshot = { id: 'cost-regression', doc_id: demoDocument.doc_id, messages: [paid, cached].flatMap((answer, n) => [
    { id: `q-${n}`, role: 'user', content: answer.question, answer: null },
    { id: `a-${n}`, role: 'assistant', content: answer.answer.text_md, answer },
  ]) }
  api.getChat.mockImplementation(async () => structuredClone(snapshot))
  await act(async () => root.render(<ChatScreen docs={[demoDocument]} loadingDocs={false} demo={false} contextDocument={null} hidden={false} onChatChange={() => {}} onOpenCitation={() => {}} />))
  const costs = () => [...host.querySelectorAll('[data-testid="answer-cost"]')].map((node) => node.textContent)
  expect(costs()).toEqual(['$0.0054', '$0.0000'])
  await act(async () => host.querySelector<HTMLButtonElement>('[aria-label="Open citation 1"]')!.click())
  expect(host.querySelector('[data-testid="open-drawing"]')?.textContent).toBe('paid-answer')
  expect(costs()).toEqual(['$0.0054', '$0.0000'])
  await act(async () => { for (const listener of live.listeners) listener({ type: 'connected' }) })
  expect(api.getChat).toHaveBeenCalledTimes(2)
  expect(costs()).toEqual(['$0.0054', '$0.0000'])
  expect(paid.cost.usd_total).toBe(0.005434)
})
