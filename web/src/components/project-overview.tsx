import { useEffect, useState } from 'react'
import { ErrorLine, Skeleton } from './project-parts'
import { projectsApi, type Project, type ProjectOverview } from '../lib/projects-api'
import { area, count, docTitle, roleLabels, severityLabel } from '../lib/projects-format'

export function useOverview(project: Project) {
  const [state, setState] = useState<{ data?: ProjectOverview; error: string }>({ error: '' })
  const [key, setKey] = useState(0)
  // The server caches by document set; ask again whenever the set changes.
  const docKey = project.docs.map((doc) => `${doc.doc_id}:${doc.role}:${doc.level ?? ''}`).join('|')
  useEffect(() => {
    if (!project.docs.length) { setState({ error: '' }); return }
    let live = true
    setState((previous) => ({ data: previous.data, error: '' }))
    projectsApi.overview(project.id).then((data) => { if (live) setState({ data, error: '' }) })
      .catch((error: unknown) => { if (live) setState({ error: error instanceof Error ? error.message : 'The overview could not be loaded.' }) })
    return () => { live = false }
  }, [project.id, docKey, key]) // eslint-disable-line react-hooks/exhaustive-deps
  return { ...state, loading: !!project.docs.length && !state.data && !state.error, retry: () => setKey((value) => value + 1) }
}
export type OverviewState = ReturnType<typeof useOverview>

export const summary = {
  totals(data?: ProjectOverview) {
    if (!data) return ''
    const parts = [[data.totals.storeys, 'storey'], [data.totals.rooms, 'room'], [data.totals.doors, 'door'], [data.totals.windows, 'window']] as const
    return parts.filter(([value]) => value != null).map(([value, word]) => `${count(value)} ${word}${value === 1 ? '' : 's'}`).join(', ')
  },
  agree(data?: ProjectOverview) {
    if (!data) return ''
    const same = data.agreements.filter((row) => row.status === 'matches').length, differ = data.agreements.length - same
    if (!data.agreements.length) return ''
    return `${same} agree${differ ? `, ${differ} differ${differ === 1 ? 's' : ''}` : ''}`
  },
  mistakes(data?: ProjectOverview) {
    if (!data) return ''
    return data.mistakes.length ? `${data.mistakes.length} to check` : 'Nothing flagged'
  },
}

function Section({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return <section className="pj-section" aria-label={title}><header><h2>{title}</h2>{note && <p>{note}</p>}</header>{children}</section>
}

export function OverviewTab({ project, overview, onShow, showBusy }: { project: Project; overview: OverviewState; onShow: (docId: string, itemIds: string[]) => void; showBusy: string | null }) {
  const { data, loading, error, retry } = overview
  const titleOf = (id: string) => { const doc = project.docs.find((item) => item.doc_id === id); return doc ? docTitle(doc) : 'Another file' }
  if (!project.docs.length) return <div className="pj-empty"><h2>Nothing to total yet</h2><p>Add files to this project and the totals, checks and cross-checks appear here.</p></div>
  if (error && !data) return <ErrorLine message={error} onRetry={retry} />
  if (loading || !data) return <div className="pj-overview" aria-busy="true" aria-label="Reading the project"><div className="overview-stats pj-stats">{[0, 1, 2, 3, 4].map((n) => <div key={n} className="overview-stat"><Skeleton lines={2} /></div>)}</div><Skeleton lines={4} /></div>
  const tiles = [['Storeys', count(data.totals.storeys)], ['Rooms', count(data.totals.rooms)], ['Doors', count(data.totals.doors)], ['Windows', count(data.totals.windows)], ['Floor area', area(data.totals.floor_area_m2)]]
  return <div className="pj-overview">
    {error && <ErrorLine message={error} onRetry={retry} />}
    <div className="overview-stats pj-stats" aria-label="Totals across all files">{tiles.map(([label, value]) => <div className="overview-stat" key={label} title={value === '–' ? 'Not available from these files' : undefined}><strong>{value}</strong><span>{label}</span></div>)}</div>

    <Section title="By level" note="Counted from the files below, level by level.">
      {data.levels.length ? <div className="pj-table" role="table" aria-label="Totals by level">
        <div className="pj-row pj-row-head" role="row"><span role="columnheader">Level</span><span role="columnheader">Rooms</span><span role="columnheader">Doors</span><span role="columnheader">Windows</span><span role="columnheader">Area</span><span role="columnheader" className="pj-from">From</span></div>
        {data.levels.map((row) => <div className="pj-row" role="row" key={row.level}><span role="cell">{row.level}</span><span role="cell">{count(row.rooms)}</span><span role="cell">{count(row.doors)}</span><span role="cell">{count(row.windows)}</span><span role="cell">{area(row.floor_area_m2)}</span><span role="cell" className="pj-from">{row.sources.length} {row.sources.length === 1 ? 'file' : 'files'}</span></div>)}
      </div> : <p className="pj-hint">No levels could be told apart yet. Set a level on a file in Files.</p>}
    </Section>

    <Section title="Sources agree" note="The same thing counted in more than one file.">
      {data.agreements.length ? <ul className="pj-list">{data.agreements.map((row, index) => <li key={`${row.what}-${index}`}>
        <div><strong>{row.what}</strong><small>{row.values.map((value) => `${titleOf(value.doc_id)}: ${String(value.value)}`).join('  ·  ')}</small></div>
        <span className={`badge ${row.status === 'matches' ? 'badge-success' : 'badge-warning'}`}>{row.status === 'matches' ? 'Matches' : 'Differs'}</span>
      </li>)}</ul> : <p className="pj-hint">Nothing is shown in more than one file yet, so there is nothing to compare.</p>}
    </Section>

    <Section title="Mistakes found" note="Checks only cover what the files show. Look at each one on the drawing.">
      {data.mistakes.length ? <ul className="pj-list pj-mistakes">{data.mistakes.map((mistake) => {
        const docId = mistake.doc_ids[0]
        return <li key={mistake.id}>
          <div><span className={`badge ${mistake.severity === 'high' ? 'badge-warning' : 'badge-neutral'}`}>{severityLabel[mistake.severity]}</span>
            <strong>{mistake.title}</strong><p>{mistake.text}</p>{mistake.check && <small>To check: {mistake.check}</small>}</div>
          {docId && <button type="button" className="button button-outline button-size-sm" disabled={showBusy === docId} onClick={() => onShow(docId, mistake.item_ids)}>{showBusy === docId ? 'Opening…' : 'Show'}</button>}
        </li>
      })}</ul> : <p className="pj-hint">Nothing flagged in these files.</p>}
    </Section>

    <Section title="Coverage" note="What each file adds to the totals.">
      {data.coverage.length ? <ul className="pj-list">{data.coverage.map((row) => <li key={row.doc_id}>
        <div><strong>{titleOf(row.doc_id)}</strong><small>{roleLabels[row.role as keyof typeof roleLabels] ?? row.role}{row.level ? ` · ${row.level}` : ''} · {row.contributes || 'nothing counted'}</small></div>
        {row.confidence_label && <span className="badge badge-neutral">{row.confidence_label}</span>}
      </li>)}</ul> : <p className="pj-hint">No coverage information yet.</p>}
    </Section>
  </div>
}
