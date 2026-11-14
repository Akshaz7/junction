import { useCallback, useEffect, useState } from 'react'
import { Folder, Plus, Search } from 'lucide-react'
import { Button } from './ui'
import { emptyChoice, ErrorLine, FilesChooser, hasChoice, ProjectDialog, Skeleton, type FileChoice } from './project-parts'
import { projectHref, projectsApi, queueUploads, type ProjectSummary } from '../lib/projects-api'
import { fileCount, relativeTime } from '../lib/projects-format'
import type { Document } from '../lib/types'

export function useProjects() {
  const [state, setState] = useState<{ projects?: ProjectSummary[]; error: string }>({ error: '' })
  const [key, setKey] = useState(0)
  useEffect(() => {
    let live = true
    projectsApi.list().then((projects) => { if (live) setState({ projects, error: '' }) })
      .catch((error: unknown) => { if (live) setState({ error: error instanceof Error ? error.message : 'Projects could not be loaded.' }) })
    return () => { live = false }
  }, [key])
  return { ...state, retry: useCallback(() => { setState({ error: '' }); setKey((value) => value + 1) }, []) }
}

export function NewProjectDialog({ docs, onClose }: { docs: Document[]; onClose: () => void }) {
  const [name, setName] = useState('')
  const [choice, setChoice] = useState<FileChoice>(emptyChoice)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function create() {
    if (!name.trim() || busy) return
    setBusy(true); setError('')
    try {
      const project = await projectsApi.create(name.trim(), choice.libraryIds)
      queueUploads(project.id, choice.files)
      onClose()
      window.location.hash = projectHref(project.id).slice(1)
    } catch (err) { setError(err instanceof Error ? err.message : 'The project could not be created.'); setBusy(false) }
  }
  return <ProjectDialog title="New project" description="One building, all its files." onClose={onClose}
    footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" disabled={!name.trim() || busy} onClick={() => void create()}>{busy ? 'Creating…' : hasChoice(choice) ? `Create with ${fileCount(choice.libraryIds.length + choice.files.length)}` : 'Create project'}</Button></>}>
    <form onSubmit={(event) => { event.preventDefault(); void create() }}>
      <label className="pj-field"><span>Name</span><input className="input" autoFocus value={name} maxLength={80} placeholder="For example, Harbour Street 12" onChange={(event) => setName(event.target.value)} /></label>
      <div className="pj-field"><span>Files</span><FilesChooser docs={docs} value={choice} onChange={setChoice} /></div>
      {error && <ErrorLine message={error} />}
    </form>
  </ProjectDialog>
}

export function ProjectList({ docs }: { docs: Document[] }) {
  const { projects, error, retry } = useProjects()
  const [query, setQuery] = useState('')
  const [tab, setTab] = useState<'all' | 'demo'>('all')
  const [creating, setCreating] = useState(false)
  useEffect(() => { try { if (sessionStorage.getItem('hologram.new-project')) { sessionStorage.removeItem('hologram.new-project'); setCreating(true) } } catch { /* optional */ } }, [])
  const hasDemo = !!projects?.some((project) => project.demo)
  const rows = (projects ?? []).filter((project) => (tab === 'all' || project.demo) && project.name.toLowerCase().includes(query.trim().toLowerCase()))
    .sort((a, b) => (Date.parse(b.updated_at || b.created_at) || 0) - (Date.parse(a.updated_at || a.created_at) || 0))
  return <section className="pj-screen" aria-label="Projects">
    <div className="pj-wrap">
      <h1 className="pj-title">Projects</h1>
      <div className="pj-toolbar">
        {hasDemo && <div className="pj-pills" role="group" aria-label="Show">
          <button type="button" aria-pressed={tab === 'all'} onClick={() => setTab('all')}>All projects</button>
          <button type="button" aria-pressed={tab === 'demo'} onClick={() => setTab('demo')}>Demo</button>
        </div>}
        <label className="pj-search pj-search-bar"><Search size={15} aria-hidden="true" /><input type="search" placeholder="Search projects" aria-label="Search projects" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
        <Button variant="primary" onClick={() => setCreating(true)}><Plus size={15} />New project</Button>
      </div>
      {error ? <ErrorLine message={error} onRetry={retry} />
        : !projects ? <div className="pj-grid" aria-busy="true" aria-label="Loading projects">{[0, 1, 2, 3].map((n) => <div key={n} className="pj-card pj-card-loading"><span className="pj-icon" /><Skeleton lines={2} /></div>)}</div>
        : !projects.length ? <div className="pj-empty">
          <h2>No projects yet</h2>
          <p>A project keeps the plans, models and scans of one building together. Ask once and the answer uses all of them.</p>
          <Button variant="primary" onClick={() => setCreating(true)}><Plus size={15} />New project</Button>
        </div>
        : !rows.length ? <p className="pj-hint pj-pad">No project matches this search.</p>
        : <ul className="pj-grid" aria-label="Projects">{rows.map((project) => <li key={project.id}>
          <a className="pj-card" href={projectHref(project.id)}>
            <span className="pj-icon" aria-hidden="true"><Folder size={18} /></span>
            <span className="pj-card-text"><strong>{project.name}</strong><small>{fileCount(project.doc_count)}{relativeTime(project.updated_at || project.created_at) && ` · ${relativeTime(project.updated_at || project.created_at)}`}</small></span>
            {project.demo && <span className="badge badge-neutral">Demo</span>}
          </a></li>)}</ul>}
    </div>
    {creating && <NewProjectDialog docs={docs} onClose={() => setCreating(false)} />}
  </section>
}
