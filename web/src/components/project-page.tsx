import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowUp, ChevronRight, Ellipsis, Plus } from 'lucide-react'
import { Button } from './ui'
import { ErrorLine, Skeleton, TypeTag } from './project-parts'
import { AddFilesDialog, FilesTab, useUploads } from './project-files'
import { OverviewTab, summary, useOverview } from './project-overview'
import { useProjectViewer } from './project-viewer'
import { ProjectList } from './project-list'
import { projectChatHref, projectsApi, type Project, type ProjectChat } from '../lib/projects-api'
import { docTitle, fileCount, isReading, relativeTime } from '../lib/projects-format'
import type { Document } from '../lib/types'

type Tab = 'chats' | 'files' | 'overview'
const tabs: { id: Tab; label: string }[] = [{ id: 'chats', label: 'Chats' }, { id: 'files', label: 'Files' }, { id: 'overview', label: 'Overview' }]

function hashState() {
  const params = new URLSearchParams(window.location.hash.split('?')[1] ?? '')
  const tab = params.get('tab')
  return { id: params.get('id'), tab: (tabs.some((item) => item.id === tab) ? tab : 'chats') as Tab }
}
function useHashState() {
  const [state, setState] = useState(hashState)
  useEffect(() => {
    const update = () => setState(hashState())
    window.addEventListener('hashchange', update)
    return () => window.removeEventListener('hashchange', update)
  }, [])
  return state
}

export function useProject(id: string | null) {
  const [state, setState] = useState<{ project?: Project; error: string }>({ error: '' })
  const [key, setKey] = useState(0)
  useEffect(() => {
    if (!id) { setState({ error: '' }); return }
    let live = true
    projectsApi.get(id).then((project) => { if (live) setState({ project, error: '' }) })
      .catch((error: unknown) => { if (live) setState({ error: error instanceof Error ? error.message : 'This project could not be loaded.' }) })
    return () => { live = false }
  }, [id, key])
  const setProject = useCallback((project: Project) => setState({ project, error: '' }), [])
  // Files being read by the server: look again until they are ready.
  const reading = !!state.project?.docs.some(isReading)
  useEffect(() => {
    if (!reading || !id) return
    const timer = setInterval(() => { projectsApi.get(id).then((project) => setState({ project, error: '' })).catch(() => undefined) }, 4000)
    return () => clearInterval(timer)
  }, [reading, id])
  return { ...state, setProject, retry: () => { setState({ error: '' }); setKey((value) => value + 1) } }
}

function Breadcrumb({ name }: { name?: string }) {
  return <nav className="pj-crumbs" aria-label="Breadcrumb"><a href="#/projects">Projects</a><ChevronRight size={14} aria-hidden="true" /><span aria-current="page">{name ?? '…'}</span></nav>
}

function ProjectMenu({ project, onRenamed }: { project: Project; onRenamed: (project: Project) => void }) {
  const [renaming, setRenaming] = useState(false)
  const [name, setName] = useState(project.name)
  const [confirm, setConfirm] = useState(false)
  const [error, setError] = useState('')
  const menu = useRef<HTMLDetailsElement>(null)
  async function save() {
    const next = name.trim()
    if (!next || next === project.name) { setRenaming(false); return }
    try { onRenamed(await projectsApi.rename(project.id, next)); setRenaming(false); setError('') } catch (err) { setError(err instanceof Error ? err.message : 'Could not rename.') }
  }
  async function remove() {
    try { await projectsApi.remove(project.id); window.location.hash = '/projects' } catch (err) { setError(err instanceof Error ? err.message : 'Could not delete.'); setConfirm(false) }
  }
  return <div className="pj-menu-host">
    {renaming ? <form className="pj-rename" onSubmit={(event) => { event.preventDefault(); void save() }}>
      <input className="input" autoFocus aria-label="Project name" value={name} maxLength={80} onChange={(event) => setName(event.target.value)} onKeyDown={(event) => { if (event.key === 'Escape') setRenaming(false) }} />
      <Button type="submit" variant="primary" size="sm">Save</Button>
    </form> : <details className="pj-menu" ref={menu} onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) { event.currentTarget.open = false; setConfirm(false) } }}>
      <summary className="button button-ghost button-size-icon" aria-label="Project actions"><Ellipsis size={18} /></summary>
      <div className="pj-menu-list">
        <button type="button" onClick={() => { setName(project.name); setRenaming(true); if (menu.current) menu.current.open = false }}>Rename</button>
        {project.demo ? <p>A demo project cannot be deleted.</p>
          : confirm ? <button type="button" className="pj-danger" onClick={() => void remove()}>Delete for good?</button>
            : <button type="button" onClick={() => setConfirm(true)}>Delete project</button>}
      </div>
    </details>}
    {error && <p className="pj-error" role="alert">{error}</p>}
  </div>
}

function AskBox({ project }: { project: Project }) {
  const [text, setText] = useState('')
  const ready = project.docs.length > 0
  function send() { if (text.trim() && ready) window.location.hash = projectChatHref(project.id, undefined, text.trim()).slice(1) }
  return <form className="pj-ask" onSubmit={(event) => { event.preventDefault(); send() }}>
    <label className="sr-only" htmlFor="project-question">Ask about this project</label>
    <textarea id="project-question" rows={2} value={text} placeholder={ready ? 'Ask about this project' : 'Add files first, then ask about them'} disabled={!ready}
      onChange={(event) => setText(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); send() } }} />
    <div><span>{ready ? `Uses all ${fileCount(project.docs.length)}` : ''}</span><Button type="submit" variant="primary" size="icon" aria-label="Ask" disabled={!text.trim() || !ready}><ArrowUp size={16} /></Button></div>
  </form>
}

function ChatsTab({ project }: { project: Project }) {
  const [state, setState] = useState<{ chats?: ProjectChat[]; error: string }>({ error: '' })
  const [key, setKey] = useState(0)
  useEffect(() => {
    let live = true
    projectsApi.chats(project.id).then((chats) => { if (live) setState({ chats, error: '' }) })
      .catch((error: unknown) => { if (live) setState({ error: error instanceof Error ? error.message : 'Chats could not be loaded.' }) })
    return () => { live = false }
  }, [project.id, key])
  if (state.error) return <ErrorLine message={state.error} onRetry={() => setKey((value) => value + 1)} />
  if (!state.chats) return <Skeleton lines={4} className="pj-skel-rows" />
  if (!state.chats.length) return <p className="pj-hint pj-pad">No chats yet. Ask a question above and it is saved here.</p>
  return <ul className="pj-chats" aria-label="Chats in this project">{[...state.chats].sort((a, b) => (Date.parse(b.created_at) || 0) - (Date.parse(a.created_at) || 0)).map((chat) => <li key={chat.id}>
    <a href={projectChatHref(project.id, chat.id)}><span>{chat.title?.trim() || 'Untitled chat'}</span><time dateTime={chat.created_at}>{relativeTime(chat.created_at)}</time></a></li>)}</ul>
}

function Panel({ title, description, action, onClick, children }: { title: string; description?: string; action?: React.ReactNode; onClick?: () => void; children?: React.ReactNode }) {
  return <section className="pj-panel" aria-label={title}>
    <header>
      {onClick ? <button type="button" className="pj-panel-title" onClick={onClick}><span className="pj-panel-h">{title}</span>{description && <span className="pj-panel-p">{description}</span>}</button> : <div className="pj-panel-title"><h2>{title}</h2>{description && <p>{description}</p>}</div>}
      {action}
    </header>
    {children}
  </section>
}

export function ProjectPage({ id, tab, docs }: { id: string; tab: Tab; docs: Document[] }) {
  const { project, error, setProject, retry } = useProject(id)
  const [adding, setAdding] = useState(false)
  const overview = useOverview(project ?? { id, name: '', demo: false, created_at: '', docs: [] })
  const viewer = useProjectViewer()
  const uploads = useUploads(project ?? { id, name: '', demo: false, created_at: '', docs: [] }, setProject)
  const go = (next: Tab) => { window.location.hash = `/projects?id=${encodeURIComponent(id)}${next === 'chats' ? '' : `&tab=${next}`}` }
  if (error && !project) return <section className="pj-screen"><div className="pj-wrap"><Breadcrumb /><ErrorLine message={error} onRetry={retry} /></div></section>
  if (!project) return <section className="pj-screen" aria-busy="true" aria-label="Loading project"><div className="pj-wrap"><Breadcrumb /><Skeleton lines={2} className="pj-skel-title" /><div className="pj-columns"><div className="pj-main"><div className="pj-ask pj-ask-loading" /></div><div className="pj-side"><div className="pj-panel"><Skeleton lines={3} /></div></div></div></div></section>
  const shown = project.docs.slice(0, 4)
  const waiting = uploads.pending.filter((row) => !row.error).length
  return <section className="pj-screen" aria-label={project.name}>
    <div className="pj-wrap">
      <div className="pj-bar"><Breadcrumb name={project.name} /><ProjectMenu project={project} onRenamed={setProject} /></div>
      <header className="pj-head"><h1 className="pj-title">{project.name}</h1>
        <p>{fileCount(project.docs.length + waiting)}{project.demo && ' · Demo project'}{relativeTime(project.created_at) && ` · Created ${relativeTime(project.created_at).toLowerCase()}`}</p></header>
      {viewer.error && <ErrorLine message={viewer.error} />}
      <div className="pj-columns">
        <div className="pj-main">
          <AskBox project={project} />
          <div className="pj-tabs" role="tablist" aria-label="Project sections">{tabs.map((item) => <button key={item.id} type="button" role="tab" id={`pj-tab-${item.id}`} aria-selected={tab === item.id} aria-controls="pj-tabpanel" onClick={() => go(item.id)}>{item.label}</button>)}</div>
          <div id="pj-tabpanel" role="tabpanel" aria-labelledby={`pj-tab-${tab}`}>
            {tab === 'chats' && <ChatsTab project={project} />}
            {tab === 'files' && <FilesTab project={project} pending={uploads.pending} onDismiss={uploads.dismiss} onProject={setProject} onAdd={() => setAdding(true)} />}
            {tab === 'overview' && <OverviewTab project={project} overview={overview} onShow={viewer.open} showBusy={viewer.busy} />}
          </div>
        </div>
        <aside className="pj-side" aria-label="About this project">
          <Panel title="Files" description={project.docs.length ? fileCount(project.docs.length) : 'Plans, models, scans and PDFs'} onClick={() => go('files')}
            action={<Button variant="ghost" size="icon-sm" aria-label="Add files" onClick={() => setAdding(true)}><Plus size={16} /></Button>}>
            {project.docs.length || uploads.pending.length ? <ul className="pj-mini">{shown.map((doc) => <li key={doc.doc_id}><button type="button" onClick={() => viewer.open(doc.doc_id)} disabled={isReading(doc)}><TypeTag doc={doc} /><span>{docTitle(doc)}</span></button></li>)}
              {project.docs.length > shown.length && <li><button type="button" className="pj-more" onClick={() => go('files')}>and {project.docs.length - shown.length} more</button></li>}</ul>
              : <button type="button" className="pj-dashed" onClick={() => setAdding(true)}>Add plans, models, scans or PDFs for this building</button>}
          </Panel>
          <Panel title="Overview" description={overview.loading ? 'Reading the files…' : summary.totals(overview.data) || 'Totals and levels across all files'} onClick={() => go('overview')} />
          <Panel title="Sources agree" description={overview.loading ? 'Comparing…' : summary.agree(overview.data) || 'Where files count the same thing'} onClick={() => go('overview')} />
          <Panel title="Mistakes found" description={overview.loading ? 'Checking…' : summary.mistakes(overview.data) || 'Checks across all files'} onClick={() => go('overview')} />
        </aside>
      </div>
    </div>
    {adding && <AddFilesDialog project={project} docs={docs} onClose={() => setAdding(false)} onProject={setProject} onUpload={uploads.add} />}
    {viewer.node}
  </section>
}

export function ProjectsScreen({ docs }: { docs: Document[] }) {
  const { id, tab } = useHashState()
  return id ? <ProjectPage key={id} id={id} tab={tab} docs={docs} /> : <ProjectList docs={docs} />
}
