import { useEffect, useMemo, useState } from 'react'
import { GitCompareArrows } from 'lucide-react'
import { workspaceApi } from '../lib/api'
import { UploadAction } from './workspace-navigation'
import type { Document } from '../lib/types'
import { loadRevisionComparison, RevisionSummary, type RevisionEntry, type RevisionFeedEntry, type RevisionComparison } from './changes-screen'
import { readChange, summariseChanges } from '../lib/change-copy'
import { latestEditedPair, ownsId, pairId, pairOf, versionOptions } from '../lib/design-versions'
import { SheetCompare, type SheetChange } from './sheet-compare'
import { VisualisePanel } from '../viewer3d/VisualiseIt'
import './compare-screen.css'

type Mode = 'Side by side' | 'Wipe' | 'Overlay'
const actionWords = { removed: 'removed', added: 'added back', moved: 'moved', material: 'material' } as const

/** 3D labels for the changed items: the reading number when on this page, and what happened (removed / moved / …). */
export function changeLabels(comparison: Pick<RevisionComparison, 'changes' | 'item_ids'>): Record<string, string> {
  const out: Record<string, string> = {}
  for (const c of comparison.changes) if (c.item_id) out[c.item_id] = `${c.n} ${c.action ? actionWords[c.action] : c.type}${c.tag ? ` · ${c.tag}` : ''}`
  for (const id of comparison.item_ids ?? []) out[id] ??= 'changed'
  return out
}
/** The "Drag to compare" pill shows on the first open only. */
let dragHintShown = false
const modes: Mode[] = ['Side by side', 'Wipe', 'Overlay']

/** Compare any two versions of a drawing: real revision series and designs saved from 3D edits. Numbered boxes match the numbered readings. */
export function CompareScreen({ docs, demo }: { docs: Document[]; demo: boolean }) {
  const [feed, setFeed] = useState<RevisionFeedEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [series, setSeries] = useState('')
  const [step, setStep] = useState(() => new URLSearchParams(window.location.hash.split('?')[1] || '').get('change') || '')
  const [comparison, setComparison] = useState<RevisionComparison | null>(null)
  const [mode, setMode] = useState<Mode>('Side by side')
  const [active, setActive] = useState<string | null>(null)
  const [page, setPage] = useState<number | null>(null)
  const [show3d, setShow3d] = useState(false)

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
      const group = map.get(key) ?? { key, title: entry.summary.edited ? `${titleOf(entry)} · edited in 3D` : titleOf(entry), steps: [] }
      group.steps.push(entry); map.set(key, group)
    }
    for (const group of map.values()) group.steps.sort((a, b) => (Date.parse(a.created_at) || 0) - (Date.parse(b.created_at) || 0))
    return [...map.values()].sort((a, b) => a.title.localeCompare(b.title))
  }, [feed, docs]) // eslint-disable-line react-hooks/exhaustive-deps
  // With nothing picked yet, open the most recently saved edited design (latest version vs the original).
  useEffect(() => { if (!step && !series) { const latest = latestEditedPair(feed.filter((entry): entry is RevisionEntry => entry.type === 'new_version')); if (latest) setStep(latest) } }, [feed]) // eslint-disable-line react-hooks/exhaustive-deps
  const group = groups.find((entry) => entry.key === series) ?? groups.find((entry) => ownsId(entry.steps, step)) ?? groups.find((entry) => /A100 - DEMOLITION/i.test(entry.title)) ?? groups[0]
  // Any two versions of the drawing can be compared when the feed numbers them; otherwise the fixed pairs.
  const versions = group ? versionOptions(group.steps) : []
  const free = versions.length > 1 && !group?.steps.some((entry) => entry.id === step) ? pairOf(group!.steps, step) : null
  const chosen = group?.steps.find((entry) => entry.id === step) ?? (free ? undefined : group?.steps[0])
  const pair = free ?? (chosen?.summary.index_a != null && chosen.summary.index_b != null ? { a: chosen.summary.index_a, b: chosen.summary.index_b } : null)
  const compareId = free ? step : chosen?.id
  const pick = (a: number, b: number | undefined) => { const id = b == null ? null : pairId(group!.steps, a, b); if (id) setStep(id) }

  useEffect(() => { setPage(null); setShow3d(false) }, [compareId])
  useEffect(() => {
    setComparison(null); setActive(null)
    if (!compareId) return
    const controller = new AbortController(); setError('')
    loadRevisionComparison(compareId, controller.signal, page).then((data) => { if (!controller.signal.aborted) setComparison(data) })
      .catch((err: Error) => { if (!controller.signal.aborted) setError(err.message) })
    return () => controller.abort()
  }, [compareId, page]) // eslint-disable-line react-hooks/exhaustive-deps

  const image = comparison?.image
  const versionLabel = (version: string | number | undefined) => typeof version === 'number' ? `Version ${version}` : version || 'Unknown version'
  const label = (entry: RevisionEntry) => `${versionLabel(entry.summary.version_a)} to ${versionLabel(entry.summary.version_b)}${entry.summary.n_changes == null ? '' : ` · ${entry.summary.n_changes} changes`}`
  const readings = (comparison?.changes ?? []).map((change) => readChange(change, image ?? { w: 1, h: 1 }))
  const reading = ({ change, text }: { change: RevisionComparison['changes'][number]; text: string }) => <article key={change.change_id} tabIndex={0} data-change-id={change.change_id} data-item-id={change.item_id} data-active={active === change.change_id || undefined} onFocus={() => setActive(change.change_id)} onBlur={() => setActive(null)} onMouseEnter={() => setActive(change.change_id)} onMouseLeave={() => setActive(null)}><span className="cmp-number">{change.n}</span><p>{text}</p></article>
  const sheetChanges = useMemo<SheetChange[]>(() => !image ? [] : (comparison?.changes ?? []).map((change) => {
    const r = readChange(change, image); const box = (change.v2 || change.v1)?.bbox_px
    return { id: change.change_id, n: change.n, kind: change.type === 'modified' ? 'edited' as const : change.type, bbox: box && box.length === 4 ? box as SheetChange['bbox'] : null, text: r.text, small: r.small }
  }), [comparison, image])
  const minor = new Set(readings.filter((entry) => entry.small).map((entry) => entry.change.change_id))
  const mainCount = readings.length - minor.size
  const boxes = (side: 'v1' | 'v2') => comparison?.changes.map((change) => {
    const box = change[side]?.bbox_px
    if (!box || !image || (minor.has(change.change_id) && active !== change.change_id)) return null
    const { w, h } = image
    return <span key={change.change_id} className={`cmp-box ${change.type}${change.action === 'moved' ? ' moved' : ''}`} data-change-id={change.change_id} data-item-id={change.item_id} data-active={active === change.change_id || undefined}
      onMouseEnter={() => setActive(change.change_id)} onMouseLeave={() => setActive(null)}
      style={{ left: `${box[0] / w * 100}%`, top: `${box[1] / h * 100}%`, width: `${(box[2] - box[0]) / w * 100}%`, height: `${(box[3] - box[1]) / h * 100}%` }}><b>{change.n}</b></span>
  })

  return <section className="compare-screen" aria-label="Compare">
    <header className="cmp-header"><div><h2><GitCompareArrows size={19} />Compare versions</h2><p>Pick a drawing and any two of its versions, including designs saved from 3D edits. Boxes show what changed: red was changed or removed, green was added, amber was moved. The numbers match the list on the right.</p></div></header>
    <div className="cmp-controls">
      <label>Drawing<select aria-label="Drawing" value={group?.key ?? ''} disabled={!groups.length} onChange={(event) => { setSeries(event.target.value); setStep('') }}>{groups.map((entry) => <option key={entry.key} value={entry.key}>{entry.title}</option>)}</select></label>
      {versions.length > 1 && pair ? <>
        <label>From<select aria-label="From version" value={pair.a} onChange={(event) => { const a = Number(event.target.value); pick(a, pair.b > a ? pair.b : versions.find((v) => v.index > a)?.index) }}>{versions.slice(0, -1).map((v) => <option key={v.index} value={v.index}>{v.label}</option>)}</select></label>
        <label>To<select aria-label="To version" value={pair.b} onChange={(event) => pick(pair.a, Number(event.target.value))}>{versions.filter((v) => v.index > pair.a || v.index === pair.b).map((v) => <option key={v.index} value={v.index}>{v.label}</option>)}</select></label>
      </> : <label>Versions<select aria-label="Versions" value={chosen?.id ?? ''} disabled={!group} onChange={(event) => setStep(event.target.value)}>{group?.steps.map((entry) => <option key={entry.id} value={entry.id}>{label(entry)}</option>)}</select></label>}
      {(comparison?.pages?.filter((p) => p.n_changes).length ?? 0) > 1 && <div className="cmp-modes" role="group" aria-label="Pages with changes">{comparison!.pages!.filter((p) => p.n_changes && p.page != null).map((p) => <button type="button" key={p.page} aria-pressed={comparison!.page === p.page} onClick={() => setPage(p.page)}>Page {p.page} ({p.n_changes})</button>)}</div>}
      <div className="cmp-modes" role="group" aria-label="Comparison mode">{modes.map((item) => <button type="button" key={item} aria-pressed={mode === item} onClick={() => setMode(item)}>{item}</button>)}</div>
    </div>
    {error && <p className="error-message" role="alert">{error}</p>}
    {loading && <p className="tools-muted" role="status">Loading versions…</p>}
    {!loading && !groups.length && !error && <div className="cmp-empty"><p className="tools-muted">No drawings with more than one version yet.</p><UploadAction>Upload a new version</UploadAction></div>}
    {compareId && !comparison && !error && <p className="tools-muted" role="status">Loading comparison…</p>}
    {comparison && !image && <RevisionSummary comparison={comparison} />}
    {comparison && image && mode !== 'Side by side' && <SheetCompare key={`${compareId}-${mode}`} hideModes initialMode={mode} showHint={!dragHintShown} onHintDone={() => { dragHintShown = true }}
      prev={{ label: comparison.v1.label, src: comparison.v1.page_image || null }} curr={{ label: comparison.v2.label, src: comparison.v2.page_image || null }} size={image} changes={sheetChanges}
      summary={<>{summariseChanges(readings)}{!!comparison.item_ids?.length && !!comparison.doc_id && <button type="button" className="button button-raised button-size-default" onClick={() => setShow3d(true)}>Show in 3D ({comparison.item_ids.length} {comparison.item_ids.length === 1 ? 'item' : 'items'})</button>}</>}
      exportName={comparison.doc_id || String(compareId)} />}
    {comparison && image && mode === 'Side by side' && <div className="cmp-body">
      <div className="cmp-sheets mode-side-by-side">
          <figure aria-label={`Older: ${comparison.v1.label}`}><figcaption>{comparison.v1.label}</figcaption><div className="cmp-page" style={{ aspectRatio: `${image.w}/${image.h}` }}><img src={comparison.v1.page_image} alt="Older version" />{boxes('v1')}</div></figure>
          <figure aria-label={`Newer: ${comparison.v2.label}`}><figcaption>{comparison.v2.label}</figcaption><div className="cmp-page" style={{ aspectRatio: `${image.w}/${image.h}` }}><img src={comparison.v2.page_image} alt="Newer version" />{boxes('v2')}</div></figure>
      </div>
      <aside className="cmp-readings" aria-label="Differences"><h3>{mainCount ? `${mainCount} ${mainCount === 1 ? 'change' : 'changes'} to look at` : 'Only minor edits'}</h3>
        <p className="cmp-summary">{summariseChanges(readings)}</p>
        {!!comparison.item_ids?.length && comparison.doc_id && <button type="button" className="button button-raised button-size-default" onClick={() => setShow3d(true)}>Show in 3D ({comparison.item_ids.length} {comparison.item_ids.length === 1 ? 'item' : 'items'})</button>}
        {readings.filter((reading) => !reading.small).map(reading)}
        {readings.some((entry) => entry.small) && <details className="cmp-small"><summary>Minor edits ({readings.filter((entry) => entry.small).length})</summary>{readings.filter((entry) => entry.small).map(reading)}</details>}
        {!comparison.changes.length && <div className="cmp-empty"><p className="tools-muted">No differences were found between these versions.</p><a className="button button-raised button-size-default" href={`#/chat?doc=${encodeURIComponent((chosen ?? group?.steps[0])?.summary.doc_id || (chosen ?? group?.steps[0])?.doc_b || comparison.doc_id)}`}>Ask about this drawing</a></div>}
        <small>{comparison.edited ? 'Compared item by item from the saved 3D edits. No AI was used. Edited versions are generated from 3D edits, not issued drawings.' : 'Found automatically by comparing the two sheets line by line. No AI was used.'}{comparison.generated_for_demo ? ' · generated for demo' : ''}</small>
      </aside>
    </div>}
    {show3d && comparison?.doc_id && comparison.item_ids?.length && <VisualisePanel docId={comparison.doc_id} highlight={comparison.item_ids}
      labels={changeLabels(comparison)} cameraTargetItemId={comparison.item_ids[0]} onClose={() => setShow3d(false)} />}
  </section>
}
