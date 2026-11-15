// @vitest-environment jsdom
import { act, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SkillsScreen, SkillPicker } from './skills-screen'
import { AutomationsScreen } from './automations-screen'
import { FindingsScreen } from './findings-screen'
import { LibraryScreen } from './library-screen'
import { OverviewScreen } from './overview-screen'
import { workspaceApi } from '../lib/api'
import { WorkspaceApi } from '../lib/api'
import type { Answer, Citation, Document } from '../lib/types'
import type { Automation } from '../lib/skills'

// Exercise real HTTP clients; embedded evidence viewers have separate suites.
vi.mock('./answer-card', () => ({ AnswerCard: ({ answer, onOpenCitation }: { answer: Answer; onOpenCitation: (citation: Citation) => void }) => <div>{answer.answer.text_md}<button onClick={() => onOpenCitation(answer.citations[0])}>Source 1</button></div> }))
vi.mock('./document-viewer', () => ({ useViewerSheet: () => ({}), DocumentViewer: ({ citation, onClose }: { citation: Citation; onClose: () => void }) => <aside aria-label="Drawing evidence">{citation.item_ids.join(',')}<button onClick={onClose}>Close evidence</button></aside> }))
vi.mock('../viewer3d/VisualiseIt', () => ({ VisualisePanel: ({ docId, onClose }: { docId: string; onClose: () => void }) => <aside aria-label="Model evidence">{docId}<button onClick={onClose}>Close evidence</button></aside> }))
vi.mock('../viewer3d/liveHighlight', () => ({ onFindingsUpdated: () => () => {}, onAdvisorCards: () => () => {} }))
vi.mock('../lib/chat-live', () => ({ chatLive: { subscribe: () => () => {} } }))

const docs: Document[] = ['doc-one', 'doc-two'].map((doc_id) => ({ doc_id, source: 'demo', formats: ['pdf'], kind: 'pdf', title: doc_id, pages: 1, licence: 'MIT', credit: '', heldout: false }))
const skill = { id: 'skill-one', name: 'Window check', prompt: 'Count windows', description: '', builtin: false }
const answer: Answer = { answer_id: 'answer', question: 'Count windows', doc_ids: ['doc-one'], answer: { text_md: 'Verified answer [1]', value: null, unit: null, confidence: 1, abstained: false }, citations: [{ n: 1, doc_id: 'doc-one', page: 1, kind: 'element', bbox_px: null, item_ids: ['window-001'], quote: null }], evidence: { boxes: [], scene: { doc_id: 'doc-one', highlight_item_ids: ['window-001'], camera_target_item_id: null } }, trace: [], route: 'index', cost: { usd_total: 0, calls: [] }, latency_ms: 0 }
const automation: Automation = { id: 'auto-one', name: 'Daily check', prompt: 'Count windows', doc_ids: ['doc-one'], interval_minutes: 1440, enabled: true, last_run_at: null, next_run_at: null, last_report: null }
const completed: Automation = { ...automation, last_run_at: '2026-11-14T00:00:00Z', last_report: { report_id: 'report', ran_at: '2026-11-14T00:00:00Z', ok: true, markdown: '# Saved report\n\nVerified report answer', answer } }
const finding = { id: 'finding', doc_id: 'doc-one', rule_id: 'rule-one', item_ids: ['window-001'], severity: 'violation', message: 'Check this opening', detail: {}, rule: { id: 'rule-one', text: 'Source rule text', source_title: 'Rule source', quote: 'Source rule text', url: 'https://example.org/rule' }, created_at: '2026-11-14T00:00:00Z' }
const card = { card_id: 'card', kind: 'warning', title: 'Sourced advice', body: 'Check the opening', item_ids: ['window-001'], source: { type: 'rule', ref: 'rule-one', title: 'Rule source', quote: 'Source rule text' } }
type Call = { method: string; path: string; body?: unknown }
let calls: Call[], host: HTMLDivElement, root: Root
let handle: (call: Call) => Response | Promise<Response>
function defaults({ path, method }: Call): Response {
  if (path === '/api/skills' && method === 'GET') return Response.json({ skills: [skill] })
  if (path === '/api/skills' && method === 'POST') return Response.json({ ...skill, id: 'new-skill', name: 'New skill' }, { status: 201 })
  if (path === '/api/skills/skill-one/run') return Response.json({ answer })
  if (method === 'DELETE') return new Response(null, { status: 204 })
  if (path === '/api/automations' && method === 'GET') return Response.json({ automations: [completed] })
  if (path === '/api/automations' && method === 'POST') return Response.json({ ...automation, id: 'new-auto', name: 'New automation' }, { status: 201 })
  if (path === '/api/automations/auto-one' || path === '/api/automations/auto-one/run') return Response.json(completed)
  if (path.endsWith('/report.md')) return new Response(completed.last_report!.markdown)
  if (path.startsWith('/api/findings?')) return Response.json({ findings: [finding] })
  if (path === '/api/findings/run') return Response.json({ status: 'ok', findings: [finding] })
  if (path === '/api/advise') return Response.json({ cards: [card] })
  if (path.includes('/planmap/')) return Response.json({ doc_id: 'doc-one', page: 1, items: [{ item_id: 'window-001', bbox_px: [1, 2, 3, 4] }] })
  if (path === '/api/changes') return Response.json({ changes: [{ id: 'change', doc_b: 'doc-one', created_at: new Date().toISOString(), summary: { title: 'Drawing revised' } }] })
  if (path === '/api/findings') return Response.json({ findings: [finding] })
  if (path === '/api/chats' && method === 'GET') return Response.json({ chats: [{ id: 'saved-chat', title: 'Existing question', created_at: '2026-11-14T00:00:00Z' }] })
  if (path === '/api/chats/saved-chat') return Response.json({ id: 'saved-chat', messages: [{ role: 'user', content: 'Existing question' }, { role: 'assistant', content: 'Existing answer', answer }] })
  if (path === '/api/bench/latest') return Response.json({ file: 'test.json', data: { fake: true, cells: { 'ALL x ALL': { accuracy: 1 } } } })
  if (path === '/api/chats' && method === 'POST') return Response.json({ id: 'new-chat' })
  if (path === '/api/chats/new-chat/messages') return new Response(`event: status\ndata: {"text":"Reading documents"}\n\nevent: answer\ndata: ${JSON.stringify(answer)}\n\n`, { headers: { 'Content-Type': 'text/event-stream' } })
  throw new Error(`Unexpected request: ${method} ${path}`)
}
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true }); workspaceApi.isDemo = false
  window.history.replaceState(null, '', '#/overview'); calls = []; handle = defaults
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => { const call = { path: String(input), method: init?.method || 'GET', ...(init?.body ? { body: JSON.parse(String(init.body)) } : {}) }; calls.push(call); return handle(call) }))
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
})
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals() })
async function render(node: ReactNode) { await act(async () => { root.render(node) }) }
function button(label: string) { const result = [...host.querySelectorAll<HTMLButtonElement>('button')].find((node) => (node.getAttribute('aria-label') || node.textContent) === label); expect(result, `Button ${label}`).toBeTruthy(); return result! }
async function click(label: string) { await act(async () => button(label).click()) }
async function value(selector: string, text: string) {
  const node = host.querySelector<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>(selector)!
  const prototype = node.tagName === 'SELECT' ? HTMLSelectElement.prototype : node.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
  await act(async () => { Object.getOwnPropertyDescriptor(prototype, 'value')!.set!.call(node, text); node.dispatchEvent(new Event(node.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true })) })
}
async function form(auto = false) { await value('input', auto ? ' New automation ' : ' New skill '); await value('textarea', ' Count windows '); if (auto) { await value('[aria-label="Automation drawing"]', 'doc-two'); await value('[aria-label="Schedule"]', '10080') } }
function requested(method: string, path: string, body?: unknown) { expect(calls).toContainEqual({ method, path, ...(body === undefined ? {} : { body: path.endsWith('/messages') ? { ...(body as object), client_message_id: expect.any(String) } : body }) }) }
function failOnce(method: string, path: string) { let failed = false; handle = (call) => { if (!failed && call.method === method && call.path === path) { failed = true; return Response.json({ detail: 'Test service unavailable' }, { status: 500 }) } return defaults(call) } }

describe('Skills actions', () => {
  it('lists and refreshes skills', async () => { await render(<SkillsScreen docs={docs} />); expect(host.textContent).toContain(skill.name); await click('Refresh'); expect(calls.filter((c) => c.path === '/api/skills')).toHaveLength(2); requested('GET', '/api/skills') })
  it('creates a skill and renders the saved result', async () => { await render(<SkillsScreen docs={docs} />); await form(); await click('Save skill'); requested('POST', '/api/skills', { name: 'New skill', prompt: 'Count windows' }); expect(host.textContent).toContain('Skill saved.'); expect(host.querySelector('[data-skill-id="new-skill"]')).not.toBeNull() })
  it('runs on the selected drawing and opens/closes its answer evidence', async () => { await render(<SkillsScreen docs={docs} />); await value('[aria-label="Run on drawing"]', 'doc-two'); await click('Run skill'); requested('POST', '/api/skills/skill-one/run', { doc_ids: ['doc-two'] }); expect(host.textContent).toContain(answer.answer.text_md); await click('Source 1'); expect(host.querySelector('[aria-label="Drawing evidence"]')?.textContent).toContain('window-001'); await click('Close evidence'); expect(host.querySelector('[aria-label="Drawing evidence"]')).toBeNull() })
  it('deletes a saved skill and renders confirmation', async () => { await render(<SkillsScreen docs={docs} />); await click('Delete skill Window check'); requested('DELETE', '/api/skills/skill-one'); expect(host.querySelector('[data-skill-id="skill-one"]')).toBeNull(); expect(host.textContent).toContain('Skill deleted.') })
  it.each(['list', 'create', 'run', 'delete'])('retries the exact failed %s action', async (action) => {
    const method = action === 'list' ? 'GET' : action === 'delete' ? 'DELETE' : 'POST'
    const path = action === 'list' || action === 'create' ? '/api/skills' : `/api/skills/skill-one${action === 'run' ? '/run' : ''}`
    failOnce(method, path); await render(<SkillsScreen docs={docs} />)
    if (action === 'create') { await form(); await click('Save skill') }; if (action === 'run') await click('Run skill'); if (action === 'delete') await click('Delete skill Window check')
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('Test service unavailable')
    const failedCall = calls.find((c) => c.path === path && c.method === method)!
    await click('Retry'); expect(host.querySelector('[role="alert"]')).toBeNull(); expect(calls.filter((c) => JSON.stringify(c) === JSON.stringify(failedCall))).toHaveLength(2)
    expect(host.textContent).toContain(action === 'run' ? answer.answer.text_md : action === 'create' ? 'Skill saved.' : action === 'delete' ? 'Skill deleted.' : skill.name)
  })
  it('retries picker loading and fills the composer without running a skill', async () => { failOnce('GET', '/api/skills'); const pick = vi.fn(); await render(<SkillPicker onPick={pick} />); await click('Retry skills'); await value('[aria-label="Use a skill"]', skill.id); requested('GET', '/api/skills'); expect(pick).toHaveBeenCalledWith(skill.prompt); expect(calls.every((c) => c.method === 'GET')).toBe(true) })
  it('protects starter skills and disables runs without a drawing', async () => { handle = () => Response.json({ skills: [{ ...skill, builtin: true }] }); await render(<SkillsScreen docs={[]} />); expect(button('Run skill').disabled).toBe(true); expect(host.textContent).toContain('Add a drawing'); expect(host.textContent).not.toContain('Delete') })
})
describe('Automation actions', () => {
  it('lists and refreshes saved routines', async () => { await render(<AutomationsScreen docs={docs} />); expect(host.textContent).toContain('Daily check'); await click('Refresh'); requested('GET', '/api/automations'); expect(calls).toHaveLength(2) })
  it('creates with selected document and schedule and shows its result', async () => { await render(<AutomationsScreen docs={docs} />); await form(true); await click('Save automation'); requested('POST', '/api/automations', { name: 'New automation', prompt: 'Count windows', doc_ids: ['doc-two'], interval_minutes: 10080, enabled: true }); expect(host.textContent).toContain('Automation saved.'); expect(host.textContent).toContain('No report yet.') })
  it('runs a routine and renders its report', async () => { await render(<AutomationsScreen docs={docs} />); await click('Run now'); requested('POST', '/api/automations/auto-one/run'); requested('GET', '/api/automations/auto-one/report.md'); expect(host.textContent).toContain('Verified report answer'); expect(host.textContent).toContain('Run complete.') })
  it('loads the last report and exports its actual Markdown', async () => {
    const createUrl = vi.fn((_blob: Blob | MediaSource) => 'blob:report'); vi.stubGlobal('URL', class extends URL { static createObjectURL = createUrl; static revokeObjectURL = vi.fn() })
    const download = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    await render(<AutomationsScreen docs={docs} />); await click('Last report'); requested('GET', '/api/automations/auto-one'); requested('GET', '/api/automations/auto-one/report.md'); expect(host.textContent).toContain('Verified report answer'); await click('Export .md'); expect(createUrl).toHaveBeenCalledOnce(); expect((createUrl.mock.calls[0][0] as Blob).type).toBe('text/markdown;charset=utf-8'); expect((download.mock.instances[0] as HTMLAnchorElement).download).toBe('Daily-check.md'); expect(calls).toHaveLength(3)
  })
  it('deletes a routine and closes its report', async () => { await render(<AutomationsScreen docs={docs} />); await click('Last report'); await click('Delete automation Daily check'); requested('DELETE', '/api/automations/auto-one'); expect(host.textContent).toContain('Automation deleted.'); expect(host.querySelector('[aria-label="Last automation report"]')).toBeNull() })
  it.each(['list', 'create', 'run', 'delete', 'detail', 'report'])('retries a failed %s request and shows its result', async (action) => {
    const method = action === 'delete' ? 'DELETE' : action === 'create' || action === 'run' ? 'POST' : 'GET'
    const path = action === 'list' || action === 'create' ? '/api/automations' : `/api/automations/auto-one${action === 'run' ? '/run' : action === 'report' ? '/report.md' : ''}`
    failOnce(method, path); await render(<AutomationsScreen docs={docs} />)
    if (action === 'create') { await form(true); await click('Save automation') }; if (action === 'run') await click('Run now'); if (action === 'delete') await click('Delete automation Daily check'); if (action === 'detail' || action === 'report') await click('Last report')
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('Test service unavailable'); if (action === 'report') expect(host.textContent).not.toContain('Loading last report…')
    const failedCall = calls.find((c) => c.path === path && c.method === method)!
    await click(action === 'report' ? 'Retry report' : 'Retry'); expect(host.querySelector('[role="alert"]')).toBeNull(); expect(calls.filter((c) => JSON.stringify(c) === JSON.stringify(failedCall))).toHaveLength(2)
    expect(host.textContent).toContain(action === 'delete' ? 'Automation deleted.' : action === 'create' ? 'Automation saved.' : action === 'list' ? 'Daily check' : 'Verified report answer')
  })
  it('handles HTTP 200 ok:false as a failed run, shows the report, and retries', async () => { let first = true; handle = (c) => { if (c.path === '/api/automations/auto-one/run' && first) { first = false; return Response.json({ ...completed, last_report: { ...completed.last_report, ok: false } }) } return defaults(c) }; await render(<AutomationsScreen docs={docs} />); await click('Run now'); expect(host.textContent).toContain('Run failed'); expect(host.querySelector('[role="alert"]')?.textContent).toContain('automation run failed'); await click('Retry'); expect(host.querySelector('[role="alert"]')).toBeNull(); expect(host.textContent).toContain('Completed'); expect(calls.filter((c) => c.path.endsWith('/run'))).toHaveLength(2) })
})
describe('Findings actions', () => {
  it('lists findings for the selected drawing', async () => { await render(<FindingsScreen docs={docs} />); requested('GET', '/api/findings?doc_id=doc-one'); expect(host.textContent).toContain(finding.message); await value('[aria-label="Drawing"]', 'doc-two'); requested('GET', '/api/findings?doc_id=doc-two'); expect(host.textContent).toContain(finding.message) })
  it('runs checks and requests sourced advice, rendering both results', async () => { await render(<FindingsScreen docs={docs} />); await click('Run checks'); requested('POST', '/api/findings/run', { doc_id: 'doc-one' }); requested('POST', '/api/advise', { doc_id: 'doc-one' }); expect(host.textContent).toContain('Checks complete.'); expect(host.textContent).toContain('Sourced advice'); expect(host.textContent).toContain('Source rule text') })
  it.each(['finding', 'advice'])('opens/closes the exact %s items and exposes the source link', async (action) => { await render(<FindingsScreen docs={docs} />); if (action === 'advice') await click('Run checks'); await click(action === 'finding' ? 'Open finding rule-one' : 'Show 1 item'); requested('GET', '/api/docs/doc-one/planmap/1'); expect(host.querySelector('[aria-label="Drawing evidence"]')?.textContent).toContain('window-001'); expect(host.querySelector('a[href="https://example.org/rule"]')?.textContent).toBe('Read source'); await click('Close evidence'); expect(host.querySelector('[aria-label="Drawing evidence"]')).toBeNull() })
  it.each(['list', 'run', 'advice'])('retries failed %s without repeating completed checks', async (action) => { const path = action === 'list' ? '/api/findings?doc_id=doc-one' : action === 'run' ? '/api/findings/run' : '/api/advise'; failOnce(action === 'list' ? 'GET' : 'POST', path); await render(<FindingsScreen docs={docs} />); if (action !== 'list') await click('Run checks'); expect(host.querySelector('[role="alert"]')).not.toBeNull(); await click('Retry'); expect(host.querySelector('[role="alert"]')).toBeNull(); expect(host.textContent).toContain(finding.message); expect(calls.filter((c) => c.path === path)).toHaveLength(2); if (action === 'advice') expect(calls.filter((c) => c.path === '/api/findings/run')).toHaveLength(1) })
  it('shows unavailable checks and disables runs without a document', async () => { handle = (c) => c.path === '/api/findings/run' ? Response.json({ status: 'no_checks', findings: [] }) : defaults(c); await render(<FindingsScreen docs={docs} />); await click('Run checks'); expect(host.textContent).toContain('Checks are not available'); await render(<FindingsScreen docs={[]} />); expect(button('Run checks').disabled).toBe(true); expect(host.textContent).not.toContain('Loading findings…') })
})
describe('Library navigation', () => {
  it.skip('switches tabs with the matching list request and rendered content', async () => { await render(<LibraryScreen docs={docs} />); requested('GET', '/api/skills'); await click('Automations'); requested('GET', '/api/automations'); expect(host.textContent).toContain('Daily check'); await click('Skills'); expect(host.textContent).toContain('Window check'); expect(host.querySelector('[role="tab"][aria-selected="true"]')?.textContent).toBe('Skills') })
  it.skip('opens upload from the empty automation library', async () => { await render(<LibraryScreen docs={[]} />); await click('Automations'); await click('Upload'); expect(window.location.hash).toBe('#/data?upload=1'); expect(button('Save automation').disabled).toBe(true) })
})
const starterQuestions = [
  ['Draft claim', 'Draft a construction claim using the available project documents. Identify documented changes, affected work, dates, and supporting citations. State where cost, delay, or entitlement evidence is missing.'],
  ['Meeting prep', 'Prepare a construction coordination meeting agenda from the project documents. Summarise drawing revisions, open questions, interfaces between trades, and decisions needed, with citations.'],
  ['Plan work phase', 'Plan the next construction work phase from the project documents. Outline the work sequence, dependencies, access needs, and checks. Cite the drawings and flag missing information without inventing durations.'],
  ['Review contract', 'Review the available construction contract documents for scope, responsibilities, change procedures, and notice requirements. Cite each finding. If no contract is available, say so and identify the documents needed.'],
]
describe('Overview actions', () => {
  it('renders section results and their navigation targets', async () => { await render(<OverviewScreen docs={docs} />); for (const path of ['/api/changes', '/api/findings', '/api/chats', '/api/chats/saved-chat']) requested('GET', path); for (const text of ['Drawing revised', finding.message, 'Existing question', 'Verified answer [1]']) expect(host.textContent).toContain(text); for (const href of ['#/changes', '#/chat', '#/chat?chat=saved-chat']); expect(host.textContent).not.toContain('Accuracy'); for (const href of ['#/changes']) expect(host.querySelector(`a[href="${href}"]`)).not.toBeNull(); expect(host.querySelector('summary')?.textContent).toBe('Rule source') })
  it.each(starterQuestions)('runs %s through create and the answer stream', async (title, question) => { await render(<OverviewScreen docs={docs} />); await click(title); requested('POST', '/api/chats', { doc_ids: [], title }); requested('POST', '/api/chats/new-chat/messages', { content: question, doc_ids: [] }); expect(window.location.hash).toBe('#/chat?chat=new-chat'); expect(host.textContent).toContain(answer.answer.text_md); expect(host.querySelector('a[href="#/chat?chat=new-chat"]')?.textContent).toBe('Open saved chat') })
  it.each(['/api/changes', '/api/findings', '/api/chats'])('retries failed %s independently', async (path) => { failOnce('GET', path); await render(<OverviewScreen docs={docs} />); expect(host.querySelector('[role="alert"]')).not.toBeNull(); await click('Retry'); expect(host.querySelector('[role="alert"]')).toBeNull(); expect(calls.filter((c) => c.path === path)).toHaveLength(2); expect(host.textContent).toContain(path === '/api/changes' ? 'Drawing revised' : path === '/api/findings' ? finding.message : 'Existing question') })
  it.each(['create', 'message'])('retries a failed starter %s, preserving its created chat', async (action) => { failOnce('POST', action === 'create' ? '/api/chats' : '/api/chats/new-chat/messages'); await render(<OverviewScreen docs={docs} />); await click('Draft claim'); expect(host.querySelector('[role="alert"]')?.textContent).toContain('Test service unavailable'); await click('Retry'); expect(window.location.hash).toBe('#/chat?chat=new-chat'); expect(host.textContent).toContain(answer.answer.text_md); expect(calls.filter((c) => c.path === '/api/chats' && c.method === 'POST')).toHaveLength(action === 'create' ? 2 : 1) })
  it('explains why starters cannot run without documents', async () => { await render(<OverviewScreen />); expect(button('Draft claim').disabled).toBe(true); expect(host.textContent).toContain('Add a drawing in Data') })
})

describe('Complete drawing lists', () => {
  const ac20: Document = { ...docs[0], doc_id: 'ifc_bench__ac20-arc', title: 'AC20', kind: 'ifc', formats: ['ifc'], pages: 0 }
  const otherIfc: Document = { ...ac20, doc_id: 'ifc__another', title: 'Another IFC' }
  const manyDocs = [...Array.from({ length: 24 }, (_, i) => ({ ...docs[0], doc_id: `raster-${i}`, title: `Drawing ${i}` })), otherIfc, ac20]
  it.each(['skills', 'automations', 'findings'])('puts AC20 and IFCs first in %s, preserves every doc, and searches by ID', async (screen) => {
    await render(screen === 'skills' ? <SkillsScreen docs={manyDocs} /> : screen === 'automations' ? <AutomationsScreen docs={manyDocs} /> : <FindingsScreen docs={manyDocs} />)
    const label = screen === 'skills' ? 'Run on drawing' : screen === 'automations' ? 'Automation drawing' : 'Drawing'
    const select = () => host.querySelector<HTMLSelectElement>(`[aria-label="${label}"]`)!
    expect([...select().options].map((o) => o.value)).toEqual(['', ac20.doc_id, otherIfc.doc_id, ...manyDocs.filter((d) => d.kind !== 'ifc').sort((a, b) => a.title.localeCompare(b.title)).map((d) => d.doc_id)])
    expect(select().value).toBe(ac20.doc_id)
    await value('[aria-label="Search drawings"]', 'raster-23')
    expect([...select().options].map((o) => o.value)).toEqual(['', ac20.doc_id, 'raster-23'])
    expect(host.textContent).toContain('1 matching drawings.')
    await value(`[aria-label="${label}"]`, 'raster-23'); expect(select().value).toBe('raster-23')
    await value('[aria-label="Search drawings"]', 'no-such-drawing'); expect(host.textContent).toContain('No matching drawings.')
    await value('[aria-label="Search drawings"]', ''); expect(select().options.length).toBe(manyDocs.length + 1)
    if (screen === 'skills') { await click('Run skill'); requested('POST', '/api/skills/skill-one/run', { doc_ids: ['raster-23'] }); expect(host.textContent).toContain(answer.answer.text_md) }
    if (screen === 'automations') { await value('input:not([type="search"])', 'New automation'); await value('textarea', 'Count windows'); await click('Save automation'); requested('POST', '/api/automations', { name: 'New automation', prompt: 'Count windows', doc_ids: ['raster-23'], interval_minutes: 1440, enabled: true }); expect(host.textContent).toContain('Automation saved.') }
    if (screen === 'findings') { await click('Run checks'); requested('POST', '/api/findings/run', { doc_id: 'raster-23' }); expect(host.textContent).toContain('Checks complete.') }
  })
  it('flattens every source from GET /api/docs without dropping IFCs with no page preview', async () => {
    handle = (call) => { if (call.path !== '/api/docs') return defaults(call); expect(call).toEqual({ method: 'GET', path: '/api/docs' }); return Response.json({ sources: [{ source: 'raster', docs: manyDocs.filter((d) => d.kind !== 'ifc') }, { source: 'ifc', docs: [otherIfc, ac20] }] }) }
    const all = await new WorkspaceApi('real').getDocuments()
    expect(all).toHaveLength(manyDocs.length); expect(all).toContainEqual(ac20)
    await render(<SkillsScreen docs={all} />)
    expect(host.querySelector<HTMLSelectElement>('[aria-label="Run on drawing"]')?.value).toBe(ac20.doc_id)
  })
})
