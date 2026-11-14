import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { GitCompareArrows } from 'lucide-react'
import { workspaceApi } from '../lib/api'
import { UploadAction } from './workspace-navigation'
import type { Document } from '../lib/types'
import { loadRevisionComparison, RevisionSummary, type RevisionEntry, type RevisionFeedEntry, type RevisionComparison } from './changes-screen'
import './compare-screen.css'

type Mode = 'Side by side' | 'Wipe' | 'Overlay'
const modes: Mode[] = ['Side by side', 'Wipe', 'Overlay']

/** Compare two versions of a drawing from the real revision series. Numbered boxes match the numbered readings. */
export function CompareScreen({ docs, demo }: { docs: Document[]; demo: boolean }) {
  const [feed, setFeed] = useState<RevisionFeedEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [series, setSeries] = useState('')
  const [step, setStep] = useState(() => new URLSearchParams(window.location.hash.split('?')[1] || '').get('change') || '')
  const [comparison, setComparison] = useState<RevisionComparison | null>(null)
  const [mode, setMode] = useState<Mode>('Side by side')
  const [wipe, setWipe] = useState(50)
  const [active, setActive] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setError('')
    workspaceApi.getChanges(controller.signal).then((rows) => { if (!controller.signal.aborted) setFeed(rows) })
      .catch((err: Error) => { if (!controller.signal.aborted) setError(err.message) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [demo])

  const titleOf = (entry: RevisionEntry) => entry.summary.title || docs.find((doc) => doc.doc_id === entry.summary.doc_id)?.title || entry.doc_b
  const groups = useMemo(() => {
    const map = new Map<string, { key: string; title: string; steps: RevisionEntry[] }>()
    for (const entry of feed) {
      if (entry.type !== 'new_version') continue
      const key = entry.summary.series_id || entry.doc_a || entry.id
      const group = map.get(key) ?? { key, title: titleOf(entry), steps: [] }
      group.steps.push(entry); map.set(key, group)
    }
    for (const group of map.values()) group.steps.sort((a, b) => (Date.parse(a.created_at) || 0) - (Date.parse(b.created_at) || 0))
    return [...map.values()].sort((a, b) => a.title.localeCompare(b.title))
  }, [feed, docs]) // eslint-disable-line react-hooks/exhaustive-deps
  const group = groups.find((entry) => entry.key === series) ?? groups.find((entry) => entry.steps.some((item) => item.id === step)) ?? groups[0]
  const chosen = group?.steps.find((entry) => entry.id === step) ?? group?.steps[0]

  useEffect(() => {
    setComparison(null); setActive(null); setWipe(50)
    if (!chosen) return
    const controller = new AbortController(); setError('')
    loadRevisionComparison(chosen.id, controller.signal).then((data) => { if (!controller.signal.aborted) setComparison(data) })
      .catch((err: Error) => { if (!controller.signal.aborted) setError(err.message) })
    return () => controller.abort()
  }, [chosen?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const image = comparison?.image
  const versionLabel = (version: string | number | undefined) => typeof version === 'number' ? `Version ${version}` : version || 'Unknown version'
  const label = (entry: RevisionEntry) => `${versionLabel(entry.summary.version_a)} to ${versionLabel(entry.summary.version_b)}${entry.summary.n_changes == null ? '' : ` · ${entry.summary.n_changes} changes`}`
  const boxes = (side: 'v1' | 'v2') => comparison?.changes.map((change) => {
    const box = change[side]?.bbox_px
    if (!box || !image) return null
    const { w, h } = image
    return <span key={change.change_id} className={`cmp-box ${change.type}`} data-change-id={change.change_id} data-active={active === change.change_id || undefined}
      onMouseEnter={() => setActive(change.change_id)} onMouseLeave={() => setActive(null)}
      style={{ left: `${box[0] / w * 100}%`, top: `${box[1] / h * 100}%`, width: `${(box[2] - box[0]) / w * 100}%`, height: `${(box[3] - box[1]) / h * 100}%` }}><b>{change.n}</b></span>
  })

  return <section className="compare-screen" aria-label="Compare">
    <header className="cmp-header"><div><h2><GitCompareArrows size={19} />Compare versions</h2><p>Pick a drawing and two of its versions to see what moved.</p></div></header>
    <div className="cmp-controls">
      <label>Drawing<select aria-label="Drawing" value={group?.key ?? ''} disabled={!groups.length} onChange={(event) => { setSeries(event.target.value); setStep('') }}>{groups.map((entry) => <option key={entry.key} value={entry.key}>{entry.title}</option>)}</select></label>
      <label>Versions<select aria-label="Versions" value={chosen?.id ?? ''} disabled={!group} onChange={(event) => setStep(event.target.value)}>{group?.steps.map((entry) => <option key={entry.id} value={entry.id}>{label(entry)}</option>)}</select></label>
      <div className="cmp-modes" role="group" aria-label="Comparison mode">{modes.map((item) => <button type="button" key={item} aria-pressed={mode === item} onClick={() => setMode(item)}>{item}</button>)}</div>
    </div>
    {error && <p className="error-message" role="alert">{error}</p>}
    {loading && <p className="tools-muted" role="status">Loading versions…</p>}
    {!loading && !groups.length && !error && <div className="cmp-empty"><p className="tools-muted">No drawings with more than one version yet.</p><UploadAction>Upload a new version</UploadAction></div>}
    {chosen && !comparison && !error && <p className="tools-muted" role="status">Loading comparison…</p>}
    {comparison && !image && <RevisionSummary comparison={comparison} />}
    {comparison && image && <div className="cmp-body">
      <div className={`cmp-sheets mode-${mode.replace(/ /g, '-').toLowerCase()}`} style={{ '--wipe': `${wipe}%`, aspectRatio: mode === 'Side by side' ? undefined : `${image.w}/${image.h}` } as CSSProperties}>
        {mode === 'Side by side' ? <>
          <figure aria-label={`Older: ${comparison.v1.label}`}><figcaption>{comparison.v1.label}</figcaption><div className="cmp-page" style={{ aspectRatio: `${image.w}/${image.h}` }}><img src={comparison.v1.page_image} alt="Older version" />{boxes('v1')}</div></figure>
          <figure aria-label={`Newer: ${comparison.v2.label}`}><figcaption>{comparison.v2.label}</figcaption><div className="cmp-page" style={{ aspectRatio: `${image.w}/${image.h}` }}><img src={comparison.v2.page_image} alt="Newer version" />{boxes('v2')}</div></figure>
        </> : <div className="cmp-page cmp-stack"><img src={comparison.v1.page_image} alt="Older version" /><img src={comparison.v2.page_image} alt="Newer version" style={{ clipPath: mode === 'Wipe' ? `inset(0 0 0 ${wipe}%)` : undefined, opacity: mode === 'Overlay' ? .5 : 1 }} />{boxes('v2')}
          {mode === 'Wipe' && <input className="cmp-wipe" type="range" min="0" max="100" value={wipe} aria-label="Wipe position" onChange={(event) => setWipe(Number(event.target.value))} />}</div>}
      </div>
      <aside className="cmp-readings" aria-label="Differences"><h3>{comparison.changes.length} {comparison.changes.length === 1 ? 'difference' : 'differences'}</h3>
        {comparison.changes.map((change) => <article key={change.change_id} tabIndex={0} data-change-id={change.change_id} data-active={active === change.change_id || undefined} onFocus={() => setActive(change.change_id)} onBlur={() => setActive(null)} onMouseEnter={() => setActive(change.change_id)} onMouseLeave={() => setActive(null)}><span className="cmp-number">{change.n}</span><p>{change.sentence}</p></article>)}
        {!comparison.changes.length && <div className="cmp-empty"><p className="tools-muted">No differences were found between these versions.</p><a className="button button-raised button-size-default" href={`#/chat?doc=${encodeURIComponent(chosen?.summary.doc_id || chosen?.doc_b || comparison.doc_id)}`}>Ask about this drawing</a></div>}
        <small>{comparison.note}</small><small>{comparison.generated_for_demo ? 'generated for demo' : `Source: ${comparison.source}`}</small>
      </aside>
    </div>}
  </section>
}
