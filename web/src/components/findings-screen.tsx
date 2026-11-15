import { useEffect, useRef, useState } from 'react'
import { ClipboardCheck, Sparkles } from 'lucide-react'
import { findingsApi, groupFindings, openFindingEvidence, type AdvisorCard, type Finding } from '../lib/findings'
import { onAdvisorCards, onFindingsUpdated } from '../viewer3d/liveHighlight'
import { sourcedCards } from '../viewer3d/advisor'
import { sourceLinkLabel, sourceLinks } from '../viewer3d/AdvisorCardView'
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
    {sourced.map((card) => <article key={card.card_id} className="advisor-card"><span className="tools-tag">{card.kind}</span><h4>{card.title}</h4><p>{card.body}</p>
      <p className="tools-muted">{card.source.title} · {card.source.ref}</p><blockquote>{card.source.quote}</blockquote>
      {sourceLinks(card.source).map((url) => <a key={url} href={url} target="_blank" rel="noreferrer">{sourceLinkLabel(url)}</a>)}
      {!!card.item_ids.length && <Button variant="raised" onClick={() => onShowItems(card.item_ids, card.body)}>Show {card.item_ids.length} {card.item_ids.length === 1 ? 'item' : 'items'}</Button>}
    </article>)}
  </section>
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
  const [viewer, setViewer] = useState<{ answer: Answer; citation: Citation } | null>(null)
  const [opening, setOpening] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const retry = useRef<() => void>(() => setRefresh((value) => value + 1))
  const operation = useRef<AbortController | null>(null)
  const sheet = useViewerSheet()
  useEffect(() => {
    const controller = new AbortController()
    setFindings([]); setCards([]); setViewer(null); setError(''); setNotice(''); setBusy(false); setOpening(false)
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
    setBusy(true); setError(''); setNotice(''); setCards([])
    try {
      const result = await findingsApi.run(docId, controller.signal)
      if (controller.signal.aborted) return
      if (result.status === 'waiting' || result.status === 'not_enough_data') { setNotice(result.detail || (result.status === 'waiting' ? 'Waiting for the drawing to finish processing' : 'Not enough readable data')); return }
      setFindings(result.findings)
      setNotice(result.status === 'no_checks' ? 'Checks are not available for this drawing yet.' : result.findings.length ? 'Checks complete.' : 'Checks complete. No findings were returned by the available rules.')
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
      {!docs.length && <p className="tools-muted">No drawings available. Add a drawing in Data to run checks.</p>}
      {!loading && !busy && !notice && !findings.length && docId && <p className="tools-muted">No saved findings. Run checks to inspect this drawing.</p>}
      {groupFindings(findings).filter((group) => group.findings.length).map((group) => <section key={group.severity} className="tools-card" aria-label={group.label}><h3>{group.label} <span className="tools-tag">{group.findings.length}</span></h3>
        <ul className="finding-list">{group.findings.map((finding) => <li key={finding.id} data-finding-id={finding.id}>
          <button type="button" className="finding-open" disabled={busy || opening} onClick={() => void showItems(finding.item_ids, finding.message)} aria-label={`Open finding ${finding.rule_id}`}><span className={`tools-tag severity-${finding.severity}`}>{finding.severity}</span><strong>{finding.rule_id}</strong><span>{finding.message}</span><small>{finding.item_ids.length} {finding.item_ids.length === 1 ? 'item' : 'items'} · Open evidence</small></button>
          <blockquote>{finding.rule.text}</blockquote><p className="tools-muted">{finding.rule.source_title || 'Source unavailable'}{finding.rule.section && ` · ${finding.rule.section}`}</p>
          {finding.rule.quote && finding.rule.quote !== finding.rule.text && <blockquote>{finding.rule.quote}</blockquote>}
          {finding.rule.url && /^https?:\/\//i.test(finding.rule.url) && <a href={finding.rule.url} target="_blank" rel="noreferrer">Read source</a>}
        </li>)}</ul>
      </section>)}
      <AdvisorCardsPanel cards={cards} onShowItems={(ids, text) => { if (!busy && !opening) void showItems(ids, text) }} />
    </section>
    {viewer && (drawing ? <DocumentViewer key={`${docId}-${viewer.citation.item_ids.join(',')}`} {...viewer} sheet={sheet} onClose={() => setViewer(null)} /> : <VisualisePanel docId={viewer.citation.doc_id} highlight={viewer.citation.item_ids} onClose={() => setViewer(null)} />)}
  </div>
}
