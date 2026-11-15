import { readChange, summariseChanges } from '../lib/change-copy'
import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight, ChevronDown, FilePlus, FileText, History, Inbox, RotateCw, Search, SlidersHorizontal, X } from 'lucide-react'
import { Button } from './ui'
import { UploadAction } from './workspace-navigation'
import { apiFetch, workspaceApi } from '../lib/api'
import type { FileDocument } from './data-screen'
import type { ChangeEntry, RuleChangeEntry, Comparison } from '../lib/types'
import { ruleChangeCard } from '../lib/rule-change'
import './changes-screen.css'
import { VersionPairCompare } from './changes-screen.pair'
import { SheetCompare, WorkedOutMark, type SheetChange } from './sheet-compare'
import { shortVersion, versionDate } from '../lib/sheet-compare'

/** The "Drag to compare" pill shows on the first open only. */
let dragHintShown = false

export type RevisionEntry = Omit<ChangeEntry, 'summary'> & {
  summary: Omit<ChangeEntry['summary'], 'n_changes' | 'version_a' | 'version_b'> & {
    n_changes?: number | null; version_a?: string | number; version_b?: string | number
    discipline?: string; sender?: string | null; recipient?: string | null; pages_a?: number | null; pages_b?: number | null
  }
}
export type RevisionFeedEntry = RevisionEntry | RuleChangeEntry
export type RevisionComparison = Omit<Comparison, 'image'> & {
  image: Comparison['image'] | null; status?: string; note?: string
  page?: number | null; pages?: { page: number | null; n_changes: number }[]
  v1: Comparison['v1'] & { doc_id?: string; pages?: number | null }
  v2: Comparison['v2'] & { doc_id?: string; pages?: number | null }
}

export async function loadRevisionComparison(id: string, signal: AbortSignal, page?: number | null): Promise<RevisionComparison> {
  if (page == null) try {
    return await workspaceApi.getComparison(id, signal)
  } catch (error) {
    // The existing client requires images. Real issues can have text or issue
    // metadata only; preserve those responses until the shared client supports them.
    if (signal.aborted || !(error instanceof Error) || error.message !== 'Comparison images are not available for this change.') throw error
  }
  if (workspaceApi.isDemo) return workspaceApi.fetchJson<RevisionComparison>(`/api/changes/${encodeURIComponent(id)}${page != null ? `?page=${page}` : ''}`, signal)
  const response = await apiFetch(`/api/changes/${encodeURIComponent(id)}${page != null ? `?page=${page}` : ''}`, { signal })
  if (!response.ok) throw new Error(`Comparison could not be loaded (${response.status}).`)
  const data = await response.json() as RevisionComparison
  if (!data.v1 || !data.v2 || !Array.isArray(data.changes)) throw new Error('Comparison is not available for this change.')
  return data
}

export function RevisionSummary({ comparison }: { comparison: RevisionComparison }) {
  return <div className="revision-summary" aria-label="Revision details">
    <p>{comparison.note || 'This issue has not been compared. No drawing changes have been inferred.'}</p>
    <div className="revision-documents">{([comparison.v1, comparison.v2]).map((version, i) => <a key={i} href={`#/data?doc=${encodeURIComponent(version.doc_id || '')}`}>
      {version.label}{version.pages != null ? ` · ${version.pages} pages` : ''}
    </a>)}</div>
    {comparison.changes.map((change) => <p key={change.change_id}>{change.n}. {readChange(change, comparison.image ?? { w: 1, h: 1 }).text}</p>)}
  </div>
}

export function ChangesScreen({ docs, demo }: { docs: FileDocument[]; demo: boolean }) {
  const [pairOpen, setPairOpen] = useState(false)
  const [feed, setFeed] = useState<RevisionFeedEntry[]>([])
  const [selected, setSelected] = useState<RevisionEntry | null>(null)
  const [comparison, setComparison] = useState<RevisionComparison | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState('')
  const [folderFilter, setFolderFilter] = useState('')
  const [disciplineFilter, setDisciplineFilter] = useState('')
  const [checkedAt, setCheckedAt] = useState<Date | null>(null)
  const [filtersOpen, setFiltersOpen] = useState(false)
  const filterBox = useRef<HTMLDivElement>(null)
  const title = (entry: RevisionEntry) => entry.summary.title || docs.find((doc) => doc.doc_id === entry.summary.doc_id)?.title || entry.summary.doc_id || entry.doc_b
  const documentFor = (entry: RevisionFeedEntry) => docs.find((doc) => doc.doc_id === entry.doc_b || doc.doc_id === (entry.type === 'rule_change' ? null : entry.summary.doc_id)) || docs.find((doc) => doc.doc_id === entry.doc_a)
  const folders = [...new Set(docs.flatMap((doc) => doc.folder ? [doc.folder] : []))].sort((a, b) => a.localeCompare(b))
  const disciplineOf = (entry: RevisionFeedEntry) => entry.type === 'rule_change' ? '' : entry.summary.discipline || (documentFor(entry) as (FileDocument & { discipline?: string }) | undefined)?.discipline || ''
  const disciplines = [...new Set(feed.map(disciplineOf).filter(Boolean))].sort()
  const image = comparison?.image
  const filtered = feed.filter((entry) => {
    if (typeFilter && entry.type !== typeFilter) return false
    if (disciplineFilter && disciplineOf(entry) !== disciplineFilter) return false
    if (folderFilter && documentFor(entry)?.folder !== folderFilter) return false
    const card = entry.type === 'rule_change' ? ruleChangeCard(entry) : null
    const text = entry.type === 'rule_change' ? `Rule source changed ${card?.title || ''} ${card?.detail || ''} ${card?.url || ''}` : `${title(entry)} ${entry.summary.headline || ''} ${disciplineOf(entry)} ${entry.summary.sender || ''} ${entry.summary.recipient || ''} ${documentFor(entry)?.folder || ''}`
    return text.toLowerCase().includes(search.trim().toLowerCase())
  }).sort((a, b) => (Date.parse(b.created_at || '') || 0) - (Date.parse(a.created_at || '') || 0))
  const groups = new Map<string, RevisionFeedEntry[]>()
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
    if (!selected || selected.type === 'new_document') return
    const controller = new AbortController()
    loadRevisionComparison(selected.id, controller.signal).then((data) => { if (!controller.signal.aborted) setComparison(data) })
      .catch((err: Error) => { if (!controller.signal.aborted) setError(err.message) })
    return () => controller.abort()
  }, [selected])
  useEffect(() => {
    if (!filtersOpen) return
    const away = (event: PointerEvent) => { if (!filterBox.current?.contains(event.target as Node)) setFiltersOpen(false) }
    const key = (event: KeyboardEvent) => { if (event.key === 'Escape') setFiltersOpen(false) }
    document.addEventListener('pointerdown', away); document.addEventListener('keydown', key)
    return () => { document.removeEventListener('pointerdown', away); document.removeEventListener('keydown', key) }
  }, [filtersOpen])
  const sheetChanges = useMemo<SheetChange[]>(() => {
    if (!comparison?.image) return []
    const size = comparison.image
    return comparison.changes.map((change) => {
      const r = readChange(change, size)
      const box = (change.v2 || change.v1)?.bbox_px
      return { id: change.change_id, n: change.n, kind: change.type === 'modified' ? 'edited' : change.type, bbox: box && box.length === 4 ? box as SheetChange['bbox'] : null, text: r.text, small: r.small }
    })
  }, [comparison])
  const summary = useMemo(() => comparison?.image ? summariseChanges(comparison.changes.map((change) => readChange(change, comparison.image!))) : '', [comparison])
  const activeFilters = [typeFilter, disciplineFilter, folderFilter].filter(Boolean).length

  return <section className={`changes-screen ${selected ? 'has-comparison' : ''} ${pairOpen ? 'has-pair-result' : ''}`} aria-label="Drawing changes">
    <VersionPairCompare docs={docs} onOpen={setPairOpen} />
    <div className="changes-refresh"><span>{loading ? 'Checking…' : checkedAt ? `Checked at ${checkedAt.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}` : 'Not checked'}</span><Button variant="raised" aria-label="Refresh changes" disabled={loading} onClick={() => setRefresh((n) => n + 1)}><RotateCw size={16} /><span>Refresh</span></Button></div>
    <div className="changes-list">
      <div className="changes-search"><label className="search-field"><Search size={14} /><input type="search" aria-label="Search changes" placeholder="Search changes..." value={search} onChange={(event) => setSearch(event.target.value)} /></label>
        <div className="changes-filter-wrap" ref={filterBox}>
          <Button variant="outline" size="icon" aria-label="Filter changes" aria-haspopup="dialog" aria-expanded={filtersOpen} data-active={activeFilters > 0 || undefined} onClick={() => setFiltersOpen((open) => !open)}><SlidersHorizontal size={16} />{activeFilters > 0 && <i className="changes-filter-dot" aria-hidden="true" />}</Button>
          {filtersOpen && <div className="changes-filters" role="dialog" aria-label="Change filters">
            <label>Type<select aria-label="Change type" value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}><option value="">All changes</option><option value="new_version">New versions</option><option value="new_document">New documents</option><option value="rule_change">Rule sources</option></select></label>
            <label>Discipline<select aria-label="Change discipline" value={disciplineFilter} onChange={(event) => setDisciplineFilter(event.target.value)}><option value="">All disciplines</option>{disciplines.map((discipline) => <option key={discipline} value={discipline}>{discipline}</option>)}</select></label>
            <label>Folder<select aria-label="Change folder" value={folderFilter} onChange={(event) => setFolderFilter(event.target.value)}><option value="">All folders</option>{folders.map((folder) => <option key={folder} value={folder}>{folder}</option>)}</select></label>
            <button type="button" className="changes-filter-clear" disabled={!activeFilters && !search} onClick={() => { setSearch(''); setTypeFilter(''); setFolderFilter(''); setDisciplineFilter('') }}><X size={12} />Clear filters</button>
          </div>}
        </div></div>
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
              const discipline = disciplineOf(entry)
              const count = entry.summary.n_changes
              const sub = entry.type === 'new_version' ? (count == null ? entry.summary.headline || 'New version' : `${count} ${count === 1 ? 'change' : 'changes'}`) : (documentFor(entry)?.folder || 'New document')
              return <button className="change-row" type="button" key={entry.id} data-change-id={entry.id} aria-pressed={entry.id === selected?.id} onClick={() => setSelected(entry)}>
                <span className={`change-tile ${type}`}>{type === 'new_version' ? <History size={14} /> : <FilePlus size={14} />}</span>
                <span className="change-row-text"><strong title={title(entry)}>{title(entry)}</strong><small>{[sub, discipline].filter(Boolean).join(' · ')}</small></span>
                <span className="change-row-meta">{entry.type === 'new_version' && <WorkedOutMark />}<time dateTime={entry.created_at}>{new Date(entry.created_at).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}</time></span>
              </button>
            })}
          </div>
        })}
      </section>)}
      {!loading && !filtered.length && <div className="changes-no-data"><p>{feed.length ? 'No changes match these filters.' : 'No changes to show yet.'}</p><UploadAction /></div>}
    </div>
    <div className="changes-detail">
      {error && <p className="error-message" role="alert">{error}</p>}
      {!selected ? <div className="changes-nothing"><span><Inbox size={24} /></span><h2>Compare two versions</h2><p>Choose version A and B above, or open a revision from the list.</p></div> : <>
        <button className="all-changes" type="button" onClick={() => setSelected(null)}><ArrowLeft size={16} />All changes</button>
        <header className="comparison-header"><div><h3>{title(selected)}</h3><p>/{documentFor(selected)?.folder || documentFor(selected)?.source || 'Drawings'}</p><div className="comparison-versions"><span className="version-tag">{selected.type === 'new_document' ? 'New document' : 'New version'}</span>{comparison && <><FileText size={13} /><span title={versionDate(comparison.v1.label) || undefined}>{shortVersion(comparison.v1.label)}</span><ArrowRight size={12} /><FileText size={13} /><span title={versionDate(comparison.v2.label) || undefined}>{shortVersion(comparison.v2.label)}</span></>}</div></div><dl><div><dt>Uploaded</dt><dd>{new Date(selected.created_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}</dd></div><div><dt>Discipline</dt><dd>{disciplineOf(selected) || 'Unspecified'}</dd></div></dl></header>
        {comparison && image ? <SheetCompare key={selected.id} prev={{ label: comparison.v1.label, src: comparison.v1.page_image || null }} curr={{ label: comparison.v2.label, src: comparison.v2.page_image || null }} size={image} changes={sheetChanges} initialMode="Wipe" showHint={!dragHintShown} onHintDone={() => { dragHintShown = true }} summary={summary} exportName={comparison.doc_id || selected.id} />
          : comparison ? <RevisionSummary comparison={comparison} /> : !error && <p className="data-empty" role="status">{selected.type === 'new_document' ? 'This is a new document; no previous revision is available.' : 'Loading comparison…'}</p>}
        {comparison && <div className="phone-comparison-summary"><span className="summary-grabber" /><strong>{title(selected)}</strong><p><span className="version-tag">New version</span>{comparison.v1.label}<ArrowRight size={12} />{comparison.v2.label}</p><small>{comparison.image ? `${comparison.changes.length} changes` : 'Drawing comparison unavailable'}{comparison.generated_for_demo ? ' · generated for demo' : ''}</small></div>}
      </>}
    </div>
  </section>
}
