import { useEffect, useRef, useState, type ReactNode } from 'react'
import { ArrowRight, CalendarClock, FileSearch, HardHat, Scale } from 'lucide-react'
import { formatPercent, formatUsd } from '../lib/dashboard'
import { chatHref, chatPreview, findingCounts, overviewApi, overviewDate, topFindings, weeklyChanges } from '../lib/overview'
import type { Document } from '../lib/types'
import './overview-screen.css'
import { workspaceApi } from '../lib/api'
import { chatLive } from '../lib/chat-live'

function useOverviewSection<T>(load: (signal: AbortSignal) => Promise<T>, liveChats = false) {
  const [state, setState] = useState<{ data?: T; loading: boolean; error: string }>({ loading: true, error: '' })
  const [live, setLive] = useState('connecting')
  useEffect(() => {
    let controller: AbortController
    function refresh() {
      controller?.abort()
      controller = new AbortController()
      const signal = controller.signal
      load(signal).then((data) => {
        if (!signal.aborted) setState({ data, loading: false, error: '' })
      }).catch((error: unknown) => {
        if (!signal.aborted) setState({ loading: false, error: error instanceof Error ? error.message : 'Could not load this section.' })
      })
    }
    refresh()
    const unsubscribe = liveChats ? chatLive.subscribe((event) => {
      if (event.type === 'connected') setLive('open')
      if (event.type === 'disconnected') setLive('connecting')
      if (event.type === 'chat.message' || event.type === 'connected') refresh()
    }) : undefined
    return () => { controller.abort(); unsubscribe?.() }
  }, [load, liveChats])
  return { ...state, live }
}

const loadChanges = (signal: AbortSignal) => overviewApi.getChanges(signal)
const loadFindings = (signal: AbortSignal) => overviewApi.getFindings(signal)
const loadChats = (signal: AbortSignal) => overviewApi.getChats(signal)
const loadBench = (signal: AbortSignal) => overviewApi.getBench(signal)
const constructionStarters = [
  { title: 'Draft claim', detail: 'Build a claim from documented changes.', icon: Scale, question: 'Draft a construction claim using the available project documents. Identify documented changes, affected work, dates, and supporting citations. State where cost, delay, or entitlement evidence is missing.' },
  { title: 'Meeting prep', detail: 'Bring the right questions to the table.', icon: CalendarClock, question: 'Prepare a construction coordination meeting agenda from the project documents. Summarise drawing revisions, open questions, interfaces between trades, and decisions needed, with citations.' },
  { title: 'Plan work phase', detail: 'Turn drawing information into next steps.', icon: HardHat, question: 'Plan the next construction work phase from the project documents. Outline the work sequence, dependencies, access needs, and checks. Cite the drawings and flag missing information without inventing durations.' },
  { title: 'Review contract', detail: 'Find obligations and gaps in the evidence.', icon: FileSearch, question: 'Review the available construction contract documents for scope, responsibilities, change procedures, and notice requirements. Cite each finding. If no contract is available, say so and identify the documents needed.' },
]

function OverviewCard({ title, href, children, loading, error }: {
  title: string; href?: string; children: ReactNode; loading: boolean; error: string
}) {
  return <section className="overview-card" aria-label={title} aria-busy={loading}>
    <header><h3>{title}</h3>{href && <a href={href} aria-label={`View ${title.toLowerCase()}`}><ArrowRight size={16} /></a>}</header>
    {loading ? <p className="overview-empty" role="status">Loading…</p> : error ? <p className="overview-empty" role="alert">{error}</p> : children}
  </section>
}

export function OverviewScreen({ docs = [] }: { docs?: Document[] }) {
  const [starting, setStarting] = useState<string | null>(null)
  const [starterError, setStarterError] = useState('')
  const [starterStatus, setStarterStatus] = useState('')
  const [createdChat, setCreatedChat] = useState<string | null>(null)
  const startingRequest = useRef(false)
  async function startChat(starter: typeof constructionStarters[number]) {
    if (startingRequest.current || !docs.length || workspaceApi.isDemo) return
    startingRequest.current = true
    const sourceRoute = window.location.hash
    setStarting(starter.title); setStarterError(''); setStarterStatus(''); setCreatedChat(null)
    try {
      const id = await workspaceApi.createChat([], starter.title)
      setCreatedChat(id)
      await workspaceApi.askQuestion(id, starter.question, [], { onStatus: setStarterStatus, onTrace: () => {} })
      if (window.location.hash === sourceRoute) window.location.hash = `/chat?chat=${encodeURIComponent(id)}`
    } catch (error) { setStarterError(error instanceof Error ? error.message : 'Could not start this chat.') }
    finally { startingRequest.current = false; setStarting(null) }
  }
  const changes = useOverviewSection(loadChanges)
  const findings = useOverviewSection(loadFindings)
  const chats = useOverviewSection(loadChats, true)
  const bench = useOverviewSection(loadBench)
  const week = weeklyChanges(changes.data || [])
  const counts = findingCounts(findings.data || [])
  const total = bench.data?.data.cells?.['ALL x ALL']
  const docTitle = (id: string) => docs.find((doc) => doc.doc_id === id)?.title || id

  return <section className="overview-screen" aria-label="Workspace overview" data-live={chats.live}>
    <header className="overview-greeting"><h2>Your workspace at a glance</h2><p>Pick up a question or see what has changed.</p></header>
    <div className="overview-grid">
      <OverviewCard title="This week's changes" href="#/changes" loading={changes.loading} error={changes.error}>
        {week.length ? <ul className="overview-list">{week.map((change) => {
          const doc = change.summary.doc_id || change.doc_b
          return <li key={change.id}><a href="#/changes" data-testid="overview-change"><strong>{change.summary.title || change.summary.headline || docTitle(doc)}</strong><span>{docTitle(doc)}</span><small><time dateTime={change.created_at}>{overviewDate(change.created_at)}</time>{change.summary.generated_for_demo && ' · generated for demo'}</small></a></li>
        })}</ul> : <p className="overview-empty">No changes this week.</p>}
      </OverviewCard>
      <OverviewCard title="Open findings" loading={findings.loading} error={findings.error}>
        {findings.data?.length ? <>
          <dl className="overview-severities" aria-label="Findings by severity">{Object.entries(counts).map(([severity, count]) => <div key={severity}><dt>{severity}</dt><dd data-testid={`overview-${severity}-count`}>{count}</dd></div>)}</dl>
          <ul className="overview-list overview-findings">{topFindings(findings.data).map((finding) => <li key={finding.id} data-testid="overview-finding"><span className={`overview-severity overview-severity-${finding.severity}`}>{finding.severity}</span><p>{finding.message}</p><small>{docTitle(finding.doc_id)}</small>{finding.rule?.source_title && <details><summary>{finding.rule.source_title}</summary>{finding.rule.quote && <blockquote>{finding.rule.quote}</blockquote>}</details>}</li>)}</ul>
        </> : <p className="overview-empty">No findings yet.</p>}
      </OverviewCard>
      <OverviewCard title="Latest answers" href="#/chat" loading={chats.loading} error={chats.error}>
        {chats.data?.length ? <ul className="overview-list">{chats.data.map((chat) => {
          const preview = chatPreview(chat)
          return <li key={chat.id}><a href={chatHref(chat.id)} data-testid="overview-chat"><strong>{preview.question}</strong><span className="overview-answer">{preview.answer}</span><small>Cost: {formatUsd(preview.cost)}</small></a></li>
        })}</ul> : <p className="overview-empty">No answers yet. Start with a question below.</p>}
      </OverviewCard>
      <OverviewCard title="Accuracy" href="#/accuracy" loading={bench.loading} error={bench.error}>
        {bench.data ? <>
          <dl className="overview-metrics"><div><dt>Accuracy</dt><dd data-testid="overview-accuracy">{formatPercent(total?.accuracy)}</dd></div><div><dt>Cost per answer</dt><dd data-testid="overview-cost-per-answer">{formatUsd(total?.cost_usd_per_answer)}</dd></div></dl>
          {bench.data.data.fake === true ? <p className="overview-run-note">test run, fake model</p> : bench.data.data.fake == null && <p className="overview-run-note">Model mode unknown.</p>}
          {bench.data.data.totals?.stopped_by_max_usd && <p className="overview-run-note">Partial run: stopped at the cost limit.</p>}
          <p className="overview-run-file">{bench.data.file}</p>
        </> : <p className="overview-empty">No bench run yet.</p>}
      </OverviewCard>
    </div>
    <section className="overview-start" aria-label="Start a question"><h3>Where shall we start?</h3><div className="overview-starters">{constructionStarters.map((starter) => {
      const Icon = starter.icon
      return <button type="button" key={starter.title} className="overview-starter" aria-label={starter.title} disabled={!!starting || !docs.length || workspaceApi.isDemo} onClick={() => void startChat(starter)}><Icon size={20} /><strong>{starter.title}</strong><span>{starter.detail}</span><ArrowRight size={14} /></button>
    })}</div>{starting && <p role="status">{starterStatus || `Starting ${starting.toLowerCase()}…`}</p>}{starterError && <p role="alert">{starterError} {createdChat && <a href={chatHref(createdChat)}>Open saved chat</a>}</p>}{workspaceApi.isDemo && <p>Connect to the workspace to start a chat.</p>}</section>
  </section>
}
