import { useEffect, useState } from 'react'
import { ChevronRight, Folder, PanelRight } from 'lucide-react'
import { TypeTag } from './project-parts'
import { useProjectViewer } from './project-viewer'
import { projectHref, projectsApi, type Project, type ProjectDoc } from '../lib/projects-api'
import { docTitle, fileCount, isReading, relativeTime, thumbUrl } from '../lib/projects-format'
import type { Document } from '../lib/types'

/** The project a chat belongs to, taken from the address (#/chat?project=ID). */
export const readChatProjectId = (active: boolean) => active ? new URLSearchParams(window.location.hash.split('?')[1] ?? '').get('project') : null

/**
 * The id is read from the address on every render, not only after an effect: opening the project chat from a project
 * page switches the view and the address in the same render, and a stale null here made the auto-sent question look
 * project-less ("Add a drawing first") before the project's documents were known.
 */
export function useChatProject(active: boolean): { id: string | null; project: Project | null; error: string } {
  const [, setTick] = useState(0)
  const id = readChatProjectId(active)
  const [state, setState] = useState<{ forId: string | null; project: Project | null; error: string }>({ forId: null, project: null, error: '' })
  useEffect(() => {
    const update = () => setTick((n) => n + 1)
    update()
    window.addEventListener('hashchange', update)
    return () => window.removeEventListener('hashchange', update)
  }, [active])
  useEffect(() => {
    if (!id) { setState({ forId: null, project: null, error: '' }); return }
    let live = true
    projectsApi.get(id).then((project) => { if (live) setState({ forId: id, project, error: '' }) })
      .catch((error: unknown) => { if (live) setState({ forId: id, project: null, error: error instanceof Error ? error.message : 'This project could not be loaded.' }) })
    return () => { live = false }
  }, [id])
  const mine = state.forId === id   // never hand back another project's record while this one loads
  return { id, project: mine ? state.project : null, error: mine ? state.error : '' }
}

const KINDS = ['raster', 'pdf', 'dxf', 'dwg', 'ifc', 'svg'] as const
/** A project file the library list has not caught up with yet (still being read): built from the project's own record. */
const fromProjectDoc = (entry: Project['docs'][number]): Document => {
  const kind = (KINDS as readonly string[]).includes(entry.kind) ? entry.kind : (entry.formats ?? []).find((f) => (KINDS as readonly string[]).includes(f)) ?? 'raster'
  return { doc_id: entry.doc_id, source: 'uploads', formats: entry.formats ?? [], kind: kind as Document['kind'], title: entry.title, pages: 1, licence: '', credit: '', heldout: false }
}

/** Every file of the project, in project order. The project is the source of truth: a file the library list lacks is still attached. */
export const projectLibraryDocs = (project: Project | null, docs: Document[]) =>
  project ? project.docs.map((entry) => docs.find((doc) => doc.doc_id === entry.doc_id) ?? fromProjectDoc(entry)) : docs

export function ChatCrumb({ project, id, title }: { project: Project | null; id: string; title?: string }) {
  return <nav className="pj-crumbs" aria-label="Breadcrumb">
    <a href={projectHref(id)}>{project?.name ?? 'Project'}</a><ChevronRight size={14} aria-hidden="true" /><span aria-current="page">{title || 'Chat'}</span>
  </nav>
}

export function PanelToggle({ open, onClick }: { open: boolean; onClick: () => void }) {
  return <button type="button" className="button button-ghost button-size-icon pj-panel-toggle" aria-label="Project content" aria-pressed={open} title="Project content" onClick={onClick}><PanelRight size={18} /></button>
}

function Tile({ doc, busy, onOpen }: { doc: ProjectDoc; busy: boolean; onOpen: () => void }) {
  const [broken, setBroken] = useState(false)
  return <li><button type="button" className="pj-tile" disabled={busy || isReading(doc)} onClick={onOpen} aria-label={`Open ${docTitle(doc)}`}>
    {!broken && <img src={thumbUrl(doc)} alt="" loading="lazy" onError={() => setBroken(true)} />}
    {broken && <span className="pj-tile-name">{docTitle(doc)}</span>}
    <span className="pj-tile-tag"><TypeTag doc={doc} /></span>
  </button></li>
}

/** "Project content": the project's files as tiles beside the chat. Clicking one opens it in the viewer. */
export function ProjectContentPanel({ project, onClose }: { project: Project; onClose?: () => void }) {
  const viewer = useProjectViewer()
  return <aside className="pj-content" aria-label="Project content">
    {onClose && <button type="button" className="pj-content-back" onClick={onClose}>← Back to chat</button>}
    <h2>Project content</h2>
    <a className="pj-content-card" href={projectHref(project.id)}>
      <span className="pj-icon" aria-hidden="true"><Folder size={16} /></span>
      <span><strong>{project.name}</strong><small>{fileCount(project.docs.length)}{relativeTime(project.created_at) && ` · created ${relativeTime(project.created_at).toLowerCase()}`}</small></span>
    </a>
    <h3>Content</h3>
    {project.docs.length ? <ul className="pj-tiles">{project.docs.map((doc) => <Tile key={doc.doc_id} doc={doc} busy={viewer.busy === doc.doc_id} onOpen={() => viewer.open(doc.doc_id)} />)}</ul>
      : <p className="pj-hint">No files yet. <a href={projectHref(project.id, 'files')}>Add files</a></p>}
    {viewer.error && <p className="pj-error" role="alert">{viewer.error}</p>}
    {viewer.node}
  </aside>
}
