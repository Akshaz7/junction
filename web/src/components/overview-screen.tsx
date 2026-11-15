import { useEffect, useRef, useState, type ReactNode } from 'react'
import { ArrowRight, CalendarClock, FileSearch, HardHat, Scale } from 'lucide-react'
import { changeSubtitle, chatHref, chatPreview, cleanTitle, groupFindings, OverviewApi, severityLabel, visibleChats, weeklyChanges } from '../lib/overview'
import type { Document } from '../lib/types'
import './overview-screen.css'
import { apiFetch, workspaceApi } from '../lib/api'

const overviewApi = new OverviewApi(apiFetch)
import { chatLive } from '../lib/chat-live'

function useOverviewSection<T>(load: (signal: AbortSignal) => Promise<T>, liveChats = false) {
  const [state, setState] = useState<{ data?: T; loading: boolean; error: string }>({ loading: true, error: '' })
  const [live, setLive] = useState('connecting')
  const [refreshKey, setRefreshKey] = useState(0)
  useEffect(() => {
    let controller: AbortController
    let settled: Promise<unknown> = Promise.resolve()
    function refresh(quiet = false) {
      controller?.abort()
      controller = new AbortController()
      const signal = controller.signal
      const current = controller
      if (!quiet) setState((previous) => ({ ...previous, loading: true, error: '' }))
      // A panel must never spin forever: after 15 s show "Not available yet" with Retry.
      const timeout = window.setTimeout(() => { if (!signal.aborted) { setState((previous) => previous.loading ? { loading: false, error: 'Not available yet.' } : previous); current.abort() } }, 15_000)
      settled = load(signal).then((data) => {
        if (!signal.aborted) setState({ data, loading: false, error: '' })
      }).catch((error: unknown) => {
        if (!signal.aborted) setState({ loading: false, error: error instanceof Error ? error.message : 'Could not load this section.' })
      }).finally(() => window.clearTimeout(timeout))
    }
    refresh()
    // Live events must not turn into a request storm: dedupe while a load is in flight and allow one refresh per 15 s.
    let inFlight = false
    let wasDown = false
    let last = Date.now()
    let trailing: ReturnType<typeof setTimeout> | undefined
    function liveRefresh() {
      if (inFlight || trailing !== undefined) return
      const wait = Math.max(0, 15_000 - (Date.now() - last))
      trailing = setTimeout(() => {
        trailing = undefined; inFlight = true; last = Date.now()
        refresh(true)
        void settled.finally(() => { inFlight = false })
      }, wait)
    }
    const unsubscribe = liveChats ? chatLive.subscribe((event) => {
      if (event.type === 'connected') { setLive('open'); if (wasDown) { wasDown = false; liveRefresh() } }
      if (event.type === 'disconnected') { setLive('connecting'); wasDown = true }
      if (event.type === 'chat.message') liveRefresh()
    }, { summaries: true }) : undefined
    return () => { controller.abort(); unsubscribe?.(); if (trailing !== undefined) clearTimeout(trailing) }
  }, [load, liveChats, refreshKey])
  return { ...state, live, retry: () => setRefreshKey((value) => value + 1) }
}

const loadChanges = (signal: AbortSignal) => overviewApi.getChanges(signal)
const loadFindings = (signal: AbortSignal) => overviewApi.getFindings(signal)
const loadChats = (signal: AbortSignal) => overviewApi.getChats(signal)
const constructionStarters = [
  { title: 'Draft claim', detail: 'Build a claim from documented changes.', icon: Scale, question: 'Draft a construction claim using the available project documents. Identify documented changes, affected work, dates, and supporting citations. State where cost, delay, or entitlement evidence is missing.' },
  { title: 'Meeting prep', detail: 'Bring the right questions to the table.', icon: CalendarClock, question: 'Prepare a construction coordination meeting agenda from the project documents. Summarise drawing revisions, open questions, interfaces between trades, and decisions needed, with citations.' },
  { title: 'Plan work phase', detail: 'Turn drawing information into next steps.', icon: HardHat, question: 'Plan the next construction work phase from the project documents. Outline the work sequence, dependencies, access needs, and checks. Cite the drawings and flag missing information without inventing durations.' },
  { title: 'Review contract', detail: 'Find obligations and gaps in the evidence.', icon: FileSearch, question: 'Review the available construction contract documents for scope, responsibilities, change procedures, and notice requirements. Cite each finding. If no contract is available, say so and identify the documents needed.' },
]

function OverviewCard({ title, href, children, loading, error, onRetry }: {
  title: string; href?: string; children: ReactNode; loading: boolean; error: string; onRetry: () => void
}) {
  return <section className="overview-card" aria-label={title} aria-busy={loading}>
    <header><h3>{title}</h3>{href && <a href={href} aria-label={`View ${title.toLowerCase()}`}><ArrowRight size={16} /></a>}</header>
    {loading ? <p className="overview-empty" role="status">Loading…</p> : error ? <p className="overview-empty" role="alert">{error} <button type="button" onClick={onRetry}>Retry</button></p> : children}
  </section>
}

export function OverviewScreen({ docs = [] }: { docs?: Document[] }) {
  const [starting, setStarting] = useState<string | null>(null)
  const [starterError, setStarterError] = useState('')
  const [starterStatus, setStarterStatus] = useState('')
  const [createdChat, setCreatedChat] = useState<string | null>(null)
  const [failedStarter, setFailedStarter] = useState<typeof constructionStarters[number] | null>(null)
  const startingRequest = useRef(false)
  async function startChat(starter: typeof constructionStarters[number], existingChat?: string) {
    if (startingRequest.current || !docs.length || workspaceApi.isDemo) return
    startingRequest.current = true
    const sourceRoute = window.location.hash
    setStarting(starter.title); setStarterError(''); setStarterStatus(''); setCreatedChat(existingChat || null); setFailedStarter(starter)
    try {
      const id = existingChat || await workspaceApi.createChat([], starter.title)
      setCreatedChat(id)
      const result = await workspaceApi.askQuestion(id, starter.question, [], { onStatus: setStarterStatus, onTrace: () => {} })
      setStarterStatus(result.answer.text_md)
      if (window.location.hash === sourceRoute) window.location.hash = `/chat?chat=${encodeURIComponent(id)}`
    } catch (error) { setStarterError(error instanceof Error ? error.message : 'Could not start this chat.') }
    finally { startingRequest.current = false; setStarting(null) }
  }
  const changes = useOverviewSection(loadChanges)
  const findings = useOverviewSection(loadFindings)
  const chats = useOverviewSection(loadChats, true)
  const week = weeklyChanges(changes.data || [])
  const groups = groupFindings(findings.data || [])
  const counts: Record<string, number> = {}
  for (const group of groups) counts[group.severity] = (counts[group.severity] || 0) + 1
  const docTitle = (id: string) => cleanTitle(docs.find((doc) => doc.doc_id === id)?.title || id)
  const buildings = [...new Set(groups.map((group) => docTitle(group.doc_id)))]
  const chatRows = visibleChats(chats.data || [])

  return <section className="overview-screen" aria-label="Workspace overview" data-live={chats.live}>
    <header className="overview-greeting"><h2>Project overview</h2><p>What is in the project, what changed, and what needs checking.</p></header>
    <div className="overview-stats" aria-label="Project at a glance">
      <a className="overview-stat" href="#/data"><strong>{docs.length}</strong><span>Drawings and models</span></a>
      <a className="overview-stat" href="#/changes"><strong>{week.length}</strong><span>New this week</span></a>
      <a className="overview-stat" href="#/chat"><strong>{chatRows.length}</strong><span>Recent answers</span></a>
      <div className="overview-stat"><strong>{groups.length}</strong><span>Checks to review</span></div>
    </div>
    <div className="overview-grid">
      <OverviewCard title="Recent uploads and revisions" href="#/changes" loading={changes.loading} error={changes.error} onRetry={changes.retry}>
        {week.length ? <ul className="overview-list">{week.map((change) => {
          const doc = change.summary.doc_id || change.doc_b
          return <li key={change.id}><a href="#/changes" data-testid="overview-change"><strong>{cleanTitle(String(change.summary.title || change.summary.headline || docTitle(doc)))}</strong><span>{changeSubtitle(change)}</span><time dateTime={change.created_at} hidden /></a></li>
        })}</ul> : <p className="overview-empty">No changes this week.</p>}
      </OverviewCard>
      <OverviewCard title="Open findings" loading={findings.loading} error={findings.error} onRetry={findings.retry}>
        {groups.length ? <>
          <p className="overview-building">{buildings.join(', ')}</p>
          <ul className="overview-list overview-findings">{groups.slice(0, 3).map((group) => <li key={group.key} data-testid="overview-finding"><span className={`overview-severity overview-severity-${group.severity}`}>{severityLabel(group.severity)}</span><p>{group.line.replace(/\s+on\s+.*$/, '')}{group.storeys.length > 0 && <>{group.storeys.length > 1 ? ' on ' : ' on '}{group.storeys.join(', ')}</>}. {group.rule && <span className="overview-rule">{group.rule}.</span>}</p>{group.finding.rule?.source_title && <details><summary>Rule source</summary><p>{group.finding.rule.source_title}</p>{group.finding.rule.quote && <blockquote>{group.finding.rule.quote}</blockquote>}</details>}</li>)}</ul>
        </> : <p className="overview-empty">No findings yet.</p>}
      </OverviewCard>
      <OverviewCard title="Latest answers" href="#/chat" loading={chats.loading} error={chats.error} onRetry={chats.retry}>
        {chatRows.length ? <ul className="overview-list">{chatRows.map((chat) => {
          const preview = chatPreview(chat)
          return <li key={chat.id}><a href={chatHref(chat.id)} data-testid="overview-chat"><strong>{preview.question}</strong><span className="overview-answer">{preview.answer}</span></a></li>
        })}</ul> : <p className="overview-empty">No answers yet. Start with a question below.</p>}
      </OverviewCard>
    </div>
    <section className="overview-start" aria-label="Start a question"><h3>Where shall we start?</h3><div className="overview-starters">{constructionStarters.map((starter) => {
      const Icon = starter.icon
      return <button type="button" key={starter.title} className="overview-starter" aria-label={starter.title} disabled={!!starting || !docs.length || workspaceApi.isDemo} onClick={() => void startChat(starter)}><Icon size={20} /><strong>{starter.title}</strong><span>{starter.detail}</span><ArrowRight size={14} /></button>
    })}</div>{(starting || starterStatus && !starterError) && <p role="status">{starterStatus || `Starting ${starting?.toLowerCase()}…`} {!starting && createdChat && <a href={chatHref(createdChat)}>Open saved chat</a>}</p>}{starterError && <p role="alert">{starterError} {failedStarter && <button type="button" disabled={!!starting} onClick={() => void startChat(failedStarter, createdChat || undefined)}>Retry</button>} {createdChat && <a href={chatHref(createdChat)}>Open saved chat</a>}</p>}{!docs.length && <p>Add a drawing in Data to start a question.</p>}{workspaceApi.isDemo && <p>Connect to the workspace to start a chat.</p>}</section>
  </section>
}
