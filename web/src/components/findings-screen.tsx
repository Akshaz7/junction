import { useEffect, useRef, useState } from 'react'
import { ClipboardCheck, Sparkles } from 'lucide-react'
import { findingsApi, groupFindings, openFindingEvidence, type AdvisorCard, type Finding } from '../lib/findings'
import { onAdvisorCards, onFindingsUpdated } from '../viewer3d/liveHighlight'
import { sourcedCards } from '../viewer3d/advisor'
import { ruleName, shortSource, sourceLinkLabel, sourceLinks } from '../viewer3d/AdvisorCardView'
import { findingsStatus, type FindingsRunResponse } from '../viewer3d/FindingsPanel'
import { DocumentViewer, useViewerSheet } from './document-viewer'
import { VisualisePanel } from '../viewer3d/VisualiseIt'
import type { Answer, Citation, Document } from '../lib/types'
import { Button } from './ui'
import { DrawingPicker, drawingDocuments } from './skills-screen'
import './findings-screen.css'

export function AdvisorCardsPanel({ cards, onShowItems }: { cards: AdvisorCard[]; onShowItems: (itemIds: string[], text: string) => void }) {
  const sourced = sourcedCards({ cards })
  return <section className="tools-card advisor-cards" aria-label="Advisor cards"><h3><Sparkles size={16} />Advisor</h3>
    {!sourced.length && <p className="tools-muted">No sourced advice for this drawing.</p>}
    {sourced.map((card) => <article key={card.card_id} className="advisor-card"><span className="tools-tag">{card.kind}</span><h4 title={card.source.ref}>{card.title}</h4><p>{card.body}</p>
      <p className="tools-muted finding-source"><span title={card.source.title}>{shortSource(card.source.title)}</span>{sourceLinks(card.source).map((url) => <span key={url}> · <a href={url} target="_blank" rel="noreferrer">{sourceLinkLabel(url)}</a></span>)}</p>
      <details className="finding-rule"><summary>Rule text</summary><blockquote>{card.source.quote}</blockquote></details>
      {!!card.item_ids.length && <Button variant="raised" onClick={() => onShowItems(card.item_ids, card.body)}>Show {card.item_ids.length} {card.item_ids.length === 1 ? 'item' : 'items'}</Button>}
      {!!card.item_total && card.item_total > card.item_ids.length && <p className="tools-muted" title="Highlighting is limited to the first 50 elements so the drawing stays readable; the check itself covered all of them.">{card.item_total} elements checked; the first {card.item_ids.length} are highlighted.</p>}
    </article>)}
  </section>
}

type RunCoverage = { checked: string[]; not_checked: { rule_id: string; reason: string }[] }
/** POST /api/findings/run: run metadata (`checked`, `not_checked`, `items_checked`, ...) and/or a `coverage` block. */
export type FindingsRunResult = Awaited<ReturnType<typeof findingsApi.run>> & Omit<FindingsRunResponse, 'findings' | 'status'> & { not_checked?: RunCoverage['not_checked'] }

/** Which rules the run checked and which it could not, from either response shape; null when the server did not say. */
export function runCoverage(result: FindingsRunResult): RunCoverage | null {
  const checked = Array.isArray(result.checked) ? result.checked : result.coverage?.checked
  if (!Array.isArray(checked)) return null
  const skipped = Array.isArray(result.not_checked) ? result.not_checked : result.coverage?.not_checked
  return { checked, not_checked: Array.isArray(skipped) ? skipped : [] }
}

/** One honest status line after a run; never an all-clear when no rule was checked or coverage is unknown. */
export function runNotice(result: FindingsRunResult): string {
  if (result.status === 'waiting') return result.detail || 'Waiting for the drawing to finish processing'
  if (result.status === 'not_enough_data') return result.detail || 'Not enough readable data'
  if (result.status === 'no_checks') return findingsStatus({ ...result, detail: result.detail || 'Checks are not available for this drawing yet.' }, true)
  const coverage = runCoverage(result)
  if (!coverage) return result.findings.length ? 'Checks complete.' : 'No findings were returned. Which checks ran is not known, so this is not an all-clear.'
  if (!coverage.checked.length && !result.findings.length) return 'No rule could be checked on this drawing, so no findings is not an all-clear.'
  const skipped = coverage.not_checked.length ? ` ${coverage.not_checked.length} ${coverage.not_checked.length === 1 ? 'rule' : 'rules'} not checked (no usable input).` : ''
  return findingsStatus({ ...result, checked: coverage.checked }, true) + skipped
}

function RunCoverageDetails({ coverage }: { coverage: RunCoverage }) {
  if (!coverage.checked.length && !coverage.not_checked.length) return null
  return <details className="finding-rule" data-testid="findings-coverage"><summary>Rules checked ({coverage.checked.length}) · not checked ({coverage.not_checked.length})</summary>
    {!!coverage.checked.length && <ul aria-label="Rules checked">{coverage.checked.map((id) => <li key={id} title={id}>{ruleName(id)}</li>)}</ul>}
    {!!coverage.not_checked.length && <ul aria-label="Rules not checked">{coverage.not_checked.map((rule) => <li key={rule.rule_id} title={rule.rule_id}>{ruleName(rule.rule_id)}: {rule.reason}</li>)}</ul>}
  </details>
}

export function FindingsScreen({ docs }: { docs: Document[] }) {
  const [chosen, setChosen] = useState('')
  const docId = chosen || drawingDocuments(docs)[0]?.doc_id || ''
  const [findings, setFindings] = useState<Finding[]>([])
  const [cards, setCards] = useState<AdvisorCard[]>([])
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [coverage, setCoverage] = useState<RunCoverage | null>(null)
  const [viewer, setViewer] = useState<{ answer: Answer; citation: Citation } | null>(null)
  const [opening, setOpening] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const retry = useRef<() => void>(() => setRefresh((value) => value + 1))
  const operation = useRef<AbortController | null>(null)
  const sheet = useViewerSheet()
  useEffect(() => {
    const controller = new AbortController()
    setFindings([]); setCards([]); setViewer(null); setError(''); setNotice(''); setCoverage(null); setBusy(false); setOpening(false)
    operation.current?.abort()
    retry.current = () => setRefresh((value) => value + 1)
    setLoading(false)
    if (!docId) return
    const refresh = () => findingsApi.list(docId, controller.signal).then((rows) => { if (!controller.signal.aborted) setFindings(rows) }).catch((err: Error) => { if (!controller.signal.aborted) setError(err.message) })
    setLoading(true)
    void refresh().finally(() => { if (!controller.signal.aborted) setLoading(false) })
    const stopFindings = onFindingsUpdated((event) => { if (event.doc_id === docId) void refresh() })
    const stopCards = onAdvisorCards((event) => { if (event.doc_id === docId && !event.chat_id) setCards(event.cards) })
    return () => { controller.abort(); operation.current?.abort(); stopFindings(); stopCards() }
  }, [docId, refresh])

  async function run() {
    retry.current = () => { void run() }
    const controller = new AbortController(); operation.current = controller
    setBusy(true); setError(''); setNotice(''); setCoverage(null); setCards([])
    try {
      const result: FindingsRunResult = await findingsApi.run(docId, controller.signal)
      if (controller.signal.aborted) return
      setNotice(runNotice(result))
      if (result.status === 'waiting' || result.status === 'not_enough_data') return
      setFindings(result.findings)
      setCoverage(runCoverage(result))
      retry.current = () => { void loadAdvice() }
      const advice = await findingsApi.advise(docId, controller.signal)
      if (!controller.signal.aborted) setCards(advice)
    } catch (err) { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : 'Checks could not be completed.') }
    finally { if (!controller.signal.aborted) setBusy(false) }
  }
  async function loadAdvice() {
    const controller = new AbortController(); operation.current = controller
    setBusy(true); setError('')
    try { const advice = await findingsApi.advise(docId, controller.signal); if (!controller.signal.aborted) setCards(advice) }
    catch (err) { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : 'Advice could not be loaded.') }
    finally { if (!controller.signal.aborted) setBusy(false) }
  }
  async function showItems(ids: string[], text: string) {
    const doc = docs.find((entry) => entry.doc_id === docId)
    if (!doc) return
    retry.current = () => { void showItems(ids, text) }
    const controller = new AbortController(); operation.current?.abort(); operation.current = controller
    setOpening(true); setError('')
    try { const evidence = await openFindingEvidence(doc, ids, text, controller.signal); if (!controller.signal.aborted) setViewer(evidence) }
    catch (err) { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : 'The evidence could not be opened.') }
    finally { if (!controller.signal.aborted) setOpening(false) }
  }
  const drawing = viewer && viewer.answer.evidence.boxes.length > 0
  return <div className={`findings-workspace ${drawing ? 'has-evidence' : ''}`}>
    <section className="tools-screen" aria-label="Findings"><header className="tools-header"><div><h2><ClipboardCheck size={19} />Findings</h2><p>Inspect your drawings against sourced rules.</p></div><a href="#/data">Documents</a></header>
      <div className="tools-controls"><DrawingPicker docs={docs} label="Drawing" value={docId} onChange={setChosen} disabled={busy || opening} />
        <Button variant="raised" disabled={!docId || busy || opening || loading} onClick={() => void run()}>{busy ? 'Running checks…' : 'Run checks'}</Button></div>
      {error && <p role="alert" className="tools-message">{error} <Button disabled={busy || opening || loading} onClick={() => retry.current()}>Retry</Button></p>}
      {(busy || opening || loading || notice) && <p role="status" className="tools-message">{busy ? 'Checking the drawing and its sources…' : opening ? 'Opening cited items…' : loading ? 'Loading findings…' : notice}</p>}
      {!busy && coverage && <RunCoverageDetails coverage={coverage} />}
      {!docs.length && <p className="tools-muted">No drawings available. Add a drawing in Data to run checks.</p>}
      {!loading && !busy && !notice && !findings.length && docId && <p className="tools-muted">No saved findings. Run checks to inspect this drawing.</p>}
      {groupFindings(findings).filter((group) => group.findings.length).map((group) => <section key={group.severity} className="tools-card" aria-label={group.label}><h3>{group.label} <span className="tools-tag">{group.findings.length}</span></h3>
        <ul className="finding-list">{group.findings.map((finding) => { const title = typeof finding.detail.title === 'string' && finding.detail.title ? finding.detail.title : ruleName(finding.rule_id); const where = typeof finding.detail.storey === 'string' ? ` on ${finding.detail.storey}` : ''; return <li key={finding.id} data-finding-id={finding.id}>
          <button type="button" className="finding-open" disabled={busy || opening} onClick={() => void showItems(finding.item_ids, finding.message)} aria-label={`Open finding ${title}`}><span className={`tools-tag severity-${finding.severity}`}>{finding.severity}</span><strong title={finding.rule_id}>{title}</strong><span>{finding.message}</span><small>{finding.item_ids.length} {finding.item_ids.length === 1 ? 'element' : 'elements'}{where} · Open evidence</small></button>
          <p className="tools-muted finding-source"><span title={finding.rule.source_title}>{shortSource(finding.rule.source_title || 'Source unavailable')}</span>{finding.rule.url && /^https?:\/\//i.test(finding.rule.url) && <> · <a href={finding.rule.url} target="_blank" rel="noreferrer">{sourceLinkLabel(finding.rule.url)}</a></>}</p>
          <details className="finding-rule"><summary>Rule text</summary><blockquote>{finding.rule.text}</blockquote>
            {finding.rule.quote && finding.rule.quote !== finding.rule.text && <blockquote>{finding.rule.quote}</blockquote>}</details>
        </li> })}</ul>
      </section>)}
      <AdvisorCardsPanel cards={cards} onShowItems={(ids, text) => { if (!busy && !opening) void showItems(ids, text) }} />
    </section>
    {viewer && (drawing ? <DocumentViewer key={`${docId}-${viewer.citation.item_ids.join(',')}`} {...viewer} sheet={sheet} onClose={() => setViewer(null)} /> : <VisualisePanel docId={viewer.citation.doc_id} highlight={viewer.citation.item_ids} onClose={() => setViewer(null)} />)}
  </div>
}
