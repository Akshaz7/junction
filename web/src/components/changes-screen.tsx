import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { ArrowLeft, ArrowRight, Check, ChevronDown, Download, FilePlus, FileText, GripVertical, History, Inbox, Maximize2, Minus, Plus, RotateCw, Search, SlidersHorizontal } from 'lucide-react'
import { Button } from './ui'
import { UploadAction } from './workspace-navigation'
import { workspaceApi } from '../lib/api'
import type { FileDocument } from './data-screen'
import type { ChangeEntry, ChangeFeedEntry, Comparison } from '../lib/types'
import { ruleChangeCard } from '../lib/rule-change'
import './changes-screen.css'

export function ChangesScreen({ docs, demo }: { docs: FileDocument[]; demo: boolean }) {
  const [feed, setFeed] = useState<ChangeFeedEntry[]>([])
  const [selected, setSelected] = useState<ChangeEntry | null>(null)
  const [comparison, setComparison] = useState<Comparison | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState('')
  const [folderFilter, setFolderFilter] = useState('')
  const [checkedAt, setCheckedAt] = useState<Date | null>(null)
  const [mode, setMode] = useState<'Plain' | 'Wipe' | 'Overlay'>('Plain')
  const [boxes, setBoxes] = useState(true)
  const [wipe, setWipe] = useState(50)
  const [zoom, setZoom] = useState(100)
  const [wiping, setWiping] = useState(false)
  const canvas = useRef<HTMLDivElement>(null)
  const title = (entry: ChangeEntry) => entry.summary.title || docs.find((doc) => doc.doc_id === entry.summary.doc_id)?.title || entry.summary.doc_id || entry.doc_b
  const documentFor = (entry: ChangeFeedEntry) => docs.find((doc) => doc.doc_id === entry.doc_b || doc.doc_id === (entry.type === 'rule_change' ? null : entry.summary.doc_id)) || docs.find((doc) => doc.doc_id === entry.doc_a)
  const folders = [...new Set(docs.flatMap((doc) => doc.folder ? [doc.folder] : []))].sort((a, b) => a.localeCompare(b))
  const filtered = feed.filter((entry) => {
    if (typeFilter && entry.type !== typeFilter) return false
    if (folderFilter && documentFor(entry)?.folder !== folderFilter) return false
    const card = entry.type === 'rule_change' ? ruleChangeCard(entry) : null
    const text = entry.type === 'rule_change' ? `Rule source changed ${card?.title || ''} ${card?.detail || ''} ${card?.url || ''}` : `${title(entry)} ${entry.summary.headline || ''} ${documentFor(entry)?.folder || ''}`
    return text.toLowerCase().includes(search.trim().toLowerCase())
  }).sort((a, b) => (Date.parse(b.created_at || '') || 0) - (Date.parse(a.created_at || '') || 0))
  const groups = new Map<string, ChangeFeedEntry[]>()
  const today = new Date(); today.setHours(0, 0, 0, 0)
  const yesterday = new Date(today); yesterday.setDate(yesterday.getDate() - 1)
  for (const entry of filtered) {
    const date = new Date(entry.created_at || '')
    const day = new Date(date); day.setHours(0, 0, 0, 0)
    const label = Number.isNaN(date.getTime()) ? '' : day.getTime() === today.getTime() ? 'Today' : day.getTime() === yesterday.getTime() ? 'Yesterday' : date.toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })
    groups.set(label, [...(groups.get(label) || []), entry])
  }
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError('')
    workspaceApi.getChanges(controller.signal).then((rows) => { if (!controller.signal.aborted) { setFeed(rows); setCheckedAt(new Date()) } })
      .catch((err: Error) => { if (!controller.signal.aborted) setError(err.message) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [demo, refresh])
  useEffect(() => {
    setComparison(null)
    setError('')
    setMode('Plain')
    setZoom(100)
    setWipe(50)
    setWiping(false)
    setBoxes(true)
    if (!selected || selected.type === 'new_document') return
    const controller = new AbortController()
    workspaceApi.getComparison(selected.id, controller.signal).then((data) => { if (!controller.signal.aborted) setComparison(data) })
      .catch((err: Error) => { if (!controller.signal.aborted) setError(err.message) })
    return () => controller.abort()
  }, [selected])

  function exportChanges() {
    if (!comparison) return
    const url = URL.createObjectURL(new Blob([JSON.stringify(comparison, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a')
    link.href = url; link.download = `${comparison.doc_id}-changes.json`; link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  return <section className={`changes-screen ${selected ? 'has-comparison' : ''}`} aria-label="Drawing changes">
    <div className="changes-refresh"><span>{loading ? 'Checking…' : checkedAt ? `Checked at ${checkedAt.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}` : 'Not checked'}</span><Button variant="raised" aria-label="Refresh changes" disabled={loading} onClick={() => setRefresh((n) => n + 1)}><RotateCw size={16} /><span>Refresh</span></Button></div>
    <div className="changes-list">
      <div className="changes-search"><label className="search-field"><Search size={14} /><input type="search" aria-label="Search changes" placeholder="Search changes..." value={search} onChange={(event) => setSearch(event.target.value)} /></label><Button variant="outline" size="icon" aria-label="Clear change filters" disabled={!search && !typeFilter && !folderFilter} onClick={() => { setSearch(''); setTypeFilter(''); setFolderFilter('') }}><SlidersHorizontal size={16} /></Button></div>
      <div className="changes-filters"><label>Type<select aria-label="Change type" value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}><option value="">All types</option><option value="new_version">New versions</option><option value="new_document">New documents</option><option value="rule_change">Rule sources</option></select></label><label>Folder<select aria-label="Change folder" value={folderFilter} onChange={(event) => setFolderFilter(event.target.value)}><option value="">All folders</option>{folders.map((folder) => <option key={folder} value={folder}>{folder}</option>)}</select></label></div>
      {[...groups].map(([date, entries]) => <section key={date} className="changes-date-group" aria-label={`Changes: ${date}`}>{date && <h2 className="changes-today">{date}<ChevronDown size={14} /></h2>}
        {(['rule_change', 'new_version', 'new_document'] as const).map((type) => {
          const rows = entries.filter((entry) => entry.type === type)
          if (!rows.length) return null
          return <div key={type} className="change-group"><h3>{type === 'rule_change' ? 'Rule sources' : type === 'new_version' ? 'New versions' : 'New documents'}<span>{rows.length}</span></h3>
            {rows.map((entry) => {
              if (entry.type === 'rule_change') {
                const card = ruleChangeCard(entry)
                return card && <article className="rule-change-card" key={card.id} data-change-id={card.id} aria-label={`Rule source changed: ${card.title}`}>
                  <strong>Rule source changed</strong><h4>{card.title}</h4>{card.detail && <p>{card.detail}</p>}
                  {card.url ? <a href={card.url} target="_blank" rel="noopener noreferrer">View rule source</a> : null}
                  {card.detectedAt && Number.isFinite(Date.parse(card.detectedAt)) && <small>Detected: <time dateTime={card.detectedAt}>{new Date(card.detectedAt).toLocaleString('en-GB')}</time></small>}<small>Findings rerun</small>
                </article>
              }
              return <button className="change-row" type="button" key={entry.id} data-change-id={entry.id} aria-pressed={entry.id === selected?.id} onClick={() => setSelected(entry)}>
                <span className={`change-tile ${type}`}>{type === 'new_version' ? <History size={16} /> : <FilePlus size={16} />}</span><span><strong>{title(entry)}</strong><small>{entry.summary.n_changes === undefined ? entry.summary.headline : `${entry.summary.n_changes} changes`}</small><small>{entry.summary.generated_for_demo ? 'generated for demo' : documentFor(entry)?.folder || documentFor(entry)?.source || 'Project documents'}</small><time dateTime={entry.created_at}>{new Date(entry.created_at).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}</time></span>
              </button>
            })}
          </div>
        })}
      </section>)}
      {!loading && !filtered.length && <div className="changes-no-data"><p>{feed.length ? 'No changes match these filters.' : 'No changes to show yet.'}</p><UploadAction /></div>}
    </div>
    <div className="changes-detail">
      {error && <p className="error-message" role="alert">{error}</p>}
      {!selected ? <div className="changes-nothing"><span><Inbox size={24} /></span><h2>Nothing open</h2><p>Pick a change from the list to read what moved.</p></div> : <>
        <button className="all-changes" type="button" onClick={() => setSelected(null)}><ArrowLeft size={16} />All changes</button>
        <header className="comparison-header"><div><h2>{title(selected)}</h2><p>/{documentFor(selected)?.folder || documentFor(selected)?.source || 'Drawings'}</p><div className="comparison-versions"><span className="version-tag">{selected.type === 'new_document' ? 'New document' : 'New version'}</span>{comparison && <><FileText size={13} />{comparison.v1.label}<ArrowRight size={12} /><FileText size={13} />{comparison.v2.label}</>}</div></div><dl><div><dt>Uploaded</dt><dd>{new Date(selected.created_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}</dd></div><div><dt>Source</dt><dd>{comparison?.generated_for_demo ? 'generated for demo' : comparison?.source || 'Project documents'}</dd></div></dl></header>
        {comparison ? <div className="comparison-box">
          <div className="comparison-toolbar"><div className="compare-segments" aria-label="Comparison mode">{(['Plain', 'Wipe', 'Overlay'] as const).map((item) => <button type="button" key={item} aria-pressed={mode === item} onClick={() => setMode(item)}>{item}</button>)}</div><label className="change-boxes"><input type="checkbox" checked={boxes} onChange={(event) => setBoxes(event.target.checked)} /><span>{boxes && <Check size={12} />}</span>Change boxes</label><span className="toolbar-spacer" /><Button variant="ghost" size="icon" aria-label="Zoom out comparison" onClick={() => setZoom((n) => Math.max(25, n - 25))}><Minus size={14} /></Button><span className="comparison-zoom">{zoom}%</span><Button variant="ghost" size="icon" aria-label="Zoom in comparison" onClick={() => setZoom((n) => Math.min(400, n + 25))}><Plus size={14} /></Button><Button variant="ghost" size="icon" aria-label="Fit comparison" onClick={() => setZoom(100)}><Maximize2 size={14} /></Button></div>
          <div className="comparison-content"><div ref={canvas} className="comparison-canvas" data-wiping={wiping || undefined} data-mode={mode} style={{ '--wipe': `${wipe}%`, '--comparison-zoom': zoom / 100 } as CSSProperties}>
            {mode === 'Wipe' && <div className="wipe-labels"><span>{comparison.v1.label}</span><span>{comparison.v2.label} · Latest</span></div>}
            <div className="comparison-sheet" style={{ aspectRatio: `${comparison.image.w}/${comparison.image.h}` }}><img src={comparison.v1.page_image} alt="Previous revision" /><img src={comparison.v2.page_image} alt="Latest revision" style={{ clipPath: mode === 'Wipe' ? `inset(0 0 0 ${wipe}%)` : undefined, opacity: mode === 'Overlay' ? .5 : 1 }} />
              {boxes && comparison.changes.map((change) => {
                const box = (change.v2 || change.v1)?.bbox_px
                if (!box) return null
                return <span key={change.change_id} className={`change-region ${change.type}`} data-change-id={change.change_id} aria-label={`Change ${change.n}: ${change.sentence}`} style={{ left: `${box[0] / comparison.image.w * 100}%`, top: `${box[1] / comparison.image.h * 100}%`, width: `${(box[2] - box[0]) / comparison.image.w * 100}%`, height: `${(box[3] - box[1]) / comparison.image.h * 100}%` }}><b>{change.n}</b></span>
              })}
            </div>
            {mode === 'Wipe' && <><div className="wipe-seam"><span><GripVertical size={16} /></span></div><input className="wipe-range" type="range" aria-label="Wipe position" min="0" max="100" value={wipe} onChange={(event) => setWipe(Number(event.target.value))}
              onPointerDown={(event) => {
                if (event.pointerType === 'mouse' && event.button !== 0) return
                event.preventDefault()
                event.currentTarget.focus()
                event.currentTarget.setPointerCapture(event.pointerId)
                const bounds = event.currentTarget.getBoundingClientRect()
                setWipe(Math.round(Math.max(0, Math.min(100, (event.clientX - bounds.left) / bounds.width * 100))))
                setWiping(true)
              }}
              onPointerMove={(event) => {
                if (!event.currentTarget.hasPointerCapture(event.pointerId)) return
                const bounds = event.currentTarget.getBoundingClientRect()
                setWipe(Math.round(Math.max(0, Math.min(100, (event.clientX - bounds.left) / bounds.width * 100))))
              }}
              onPointerUp={(event) => { if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId); setWiping(false) }}
              onPointerCancel={() => setWiping(false)} onLostPointerCapture={() => setWiping(false)} /></>}
          </div><aside className="comparison-readings" aria-label="Change readings"><header><span>{comparison.v1.label}</span><span>{comparison.v2.label}</span><button type="button" onClick={exportChanges}><Download size={12} />Export</button></header>{comparison.changes.map((change) => <article key={change.change_id} data-change-id={change.change_id}><span className="reading-number">{change.n}</span><div className="change-thumbnails"><img src={comparison.v1.thumb} alt={`Before change ${change.n}`} /><img src={comparison.v2.thumb} alt={`After change ${change.n}`} /></div><p>{change.sentence}</p></article>)}</aside></div>
        </div> : !error && <p className="data-empty" role="status">{selected.type === 'new_document' ? 'This is a new document; no previous revision is available.' : 'Loading comparison…'}</p>}
        {comparison && <div className="phone-comparison-summary"><span className="summary-grabber" /><strong>{title(selected)}</strong><p><span className="version-tag">New version</span>{comparison.v1.label}<ArrowRight size={12} />{comparison.v2.label}</p><small>{comparison.changes.length} changes{comparison.generated_for_demo ? ' · generated for demo' : ''}</small></div>}
      </>}
    </div>
  </section>
}
