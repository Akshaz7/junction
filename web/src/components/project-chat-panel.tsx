import { useEffect, useState } from 'react'
import { ChevronRight, Folder, PanelRight } from 'lucide-react'
import { TypeTag } from './project-parts'
import { useProjectViewer } from './project-viewer'
import { projectHref, projectsApi, type Project, type ProjectDoc } from '../lib/projects-api'
import { docTitle, fileCount, isReading, relativeTime, thumbUrl } from '../lib/projects-format'
import type { Document } from '../lib/types'

/** The project a chat belongs to, taken from the address (#/chat?project=ID). */
export function useChatProject(active: boolean): { id: string | null; project: Project | null; error: string } {
  const read = () => active ? new URLSearchParams(window.location.hash.split('?')[1] ?? '').get('project') : null
  const [id, setId] = useState(read)
  const [state, setState] = useState<{ project: Project | null; error: string }>({ project: null, error: '' })
  useEffect(() => {
    const update = () => setId(read())
    update()
    window.addEventListener('hashchange', update)
    return () => window.removeEventListener('hashchange', update)
  }, [active]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!id) { setState({ project: null, error: '' }); return }
    let live = true
    projectsApi.get(id).then((project) => { if (live) setState({ project, error: '' }) })
      .catch((error: unknown) => { if (live) setState({ project: null, error: error instanceof Error ? error.message : 'This project could not be loaded.' }) })
    return () => { live = false }
  }, [id])
  return { id, ...state }
}

/** The library documents that belong to the project, in project order. */
export const projectLibraryDocs = (project: Project | null, docs: Document[]) =>
  project ? project.docs.flatMap((entry) => docs.find((doc) => doc.doc_id === entry.doc_id) ?? []) : docs

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
export function ProjectContentPanel({ project }: { project: Project }) {
  const viewer = useProjectViewer()
  return <aside className="pj-content" aria-label="Project content">
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
