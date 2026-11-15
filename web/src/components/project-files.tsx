import { useCallback, useEffect, useRef, useState } from 'react'
import { Ellipsis, Layers, Plus, Upload } from 'lucide-react'
import { Button } from './ui'
import { emptyChoice, ErrorLine, FilesChooser, hasChoice, ProjectDialog, type FileChoice } from './project-parts'
import { DocumentDetail, ExplorerBrowser, FileRow, FolderItem } from './file-explorer'
import { UPLOAD_ACCEPT, validateUpload } from '../lib/upload-state'
import { projectChatHref, projectRoles, projectsApi, takeUploads, type Project, type ProjectDoc, type ProjectRole } from '../lib/projects-api'
import { docTitle, isFailed, isReading, rolePlural, roleLabels } from '../lib/projects-format'
import type { Document } from '../lib/types'

export type PendingUpload = { key: string; name: string; error?: string }

/** Uploads files into the project one at a time; each shows as a row until the server returns it. */
export function useUploads(project: Project, onProject: (project: Project) => void) {
  const [pending, setPending] = useState<PendingUpload[]>([])
  const running = useRef(Promise.resolve())
  const add = useCallback((files: File[]) => {
    const rows = files.map((file) => ({ key: `${file.name}-${file.size}-${Math.random()}`, name: file.name, file }))
    setPending((previous) => [...previous, ...rows.map(({ key, name }) => ({ key, name }))])
    for (const row of rows) {
      running.current = running.current.then(async () => {
        try {
          const result = await projectsApi.upload(project.id, row.file)
          onProject(result.project)
          setPending((previous) => previous.filter((item) => item.key !== row.key))
        } catch (error) {
          setPending((previous) => previous.map((item) => item.key === row.key ? { ...item, error: error instanceof Error ? error.message : 'The upload failed.' } : item))
        }
      })
    }
  }, [project.id, onProject])
  const dismiss = useCallback((key: string) => setPending((previous) => previous.filter((item) => item.key !== key)), [])
  // Files picked in "New project" arrive through a one-time queue.
  const started = useRef<string | null>(null)
  useEffect(() => {
    if (started.current === project.id) return
    started.current = project.id
    const queued = takeUploads(project.id)
    if (queued.length) add(queued)
  }, [project.id, add])
  return { pending, add, dismiss }
}

export function AddFilesDialog({ project, docs, onClose, onProject, onUpload }: { project: Project; docs: Document[]; onClose: () => void; onProject: (project: Project) => void; onUpload: (files: File[]) => void }) {
  const [choice, setChoice] = useState<FileChoice>(emptyChoice)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function add() {
    setBusy(true); setError('')
    try {
      if (choice.libraryIds.length) onProject(await projectsApi.addDocs(project.id, choice.libraryIds))
      onUpload(choice.files)
      onClose()
    } catch (err) { setError(err instanceof Error ? err.message : 'The files could not be added.'); setBusy(false) }
  }
  const total = choice.libraryIds.length + choice.files.length
  return <ProjectDialog title="Add files" description="Plans, models, scans or PDFs for this building." onClose={onClose}
    footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" disabled={!hasChoice(choice) || busy} onClick={() => void add()}>{busy ? 'Adding…' : total ? `Add ${total} ${total === 1 ? 'file' : 'files'}` : 'Add files'}</Button></>}>
    <FilesChooser docs={docs} taken={project.docs.map((doc) => doc.doc_id)} value={choice} onChange={setChoice} />
    {error && <ErrorLine message={error} />}
  </ProjectDialog>
}

function EditFileDialog({ project, doc, onClose, onProject }: { project: Project; doc: ProjectDoc; onClose: () => void; onProject: (project: Project) => void }) {
  const [role, setRole] = useState<ProjectRole>(doc.role)
  const [level, setLevel] = useState(doc.level ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function save() {
    setBusy(true); setError('')
    try { onProject(await projectsApi.updateDoc(project.id, doc.doc_id, { role, level: level.trim() || null })); onClose() }
    catch (err) { setError(err instanceof Error ? err.message : 'That change could not be saved.'); setBusy(false) }
  }
  return <ProjectDialog title="Type and level" description={docTitle(doc)} onClose={onClose}
    footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" disabled={busy} onClick={() => void save()}>{busy ? 'Saving…' : 'Save'}</Button></>}>
    <div className="pj-fields">
      <label>Type<select className="pj-cell-input" aria-label="Type" value={role} onChange={(event) => setRole(event.target.value as ProjectRole)}>{projectRoles.map((item) => <option key={item} value={item}>{roleLabels[item]}</option>)}</select></label>
      <label>Level<input className="pj-cell-input" aria-label="Level" value={level} placeholder="For example Level 2" maxLength={60} onChange={(event) => setLevel(event.target.value)} /></label>
    </div>
    {error && <ErrorLine message={error} />}
  </ProjectDialog>
}

function RowMenu({ doc, busy, onEdit, onAsk, onRemove }: { doc: ProjectDoc; busy: boolean; onEdit: () => void; onAsk: () => void; onRemove: () => void }) {
  const menu = useRef<HTMLDetailsElement>(null)
  const act = (action: () => void) => () => { if (menu.current) menu.current.open = false; action() }
  return <details className="pj-menu pj-row-menu" ref={menu} onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) event.currentTarget.open = false }}>
    <summary className="button button-ghost button-size-icon" aria-label={`Actions for ${docTitle(doc)}`}><Ellipsis size={18} /></summary>
    <div className="pj-menu-list">
      <button type="button" onClick={act(onEdit)}>Change type and level</button>
      <button type="button" onClick={act(onAsk)}>Ask about this project</button>
      <button type="button" className="pj-danger" disabled={busy} aria-label={`Remove ${docTitle(doc)} from project`} onClick={act(onRemove)}>Remove from project</button>
    </div>
  </details>
}

const toDocument = (doc: ProjectDoc, library: Document[]): Document => {
  const known = library.find((item) => item.doc_id === doc.doc_id)
  return { ...(known ?? { source: 'project', pages: 1, licence: '', credit: '', heldout: false }), doc_id: doc.doc_id, title: docTitle(doc), formats: doc.formats?.length ? doc.formats : known?.formats ?? [], kind: (known?.kind ?? doc.kind) as Document['kind'] }
}
const rowMeta = (doc: ProjectDoc) => [roleLabels[doc.role], doc.level].filter(Boolean).join(' · ')
const rowStatus = (doc: ProjectDoc) => isFailed(doc) ? 'Could not be read' : isReading(doc) ? 'Reading the file…' : doc.role_source === 'user' ? 'Set by you' : ''

/** The Data screen's explorer for one project: folders are the file types, rows open the same viewer in place. */
export function FilesTab({ project, docs = [], pending, onDismiss, onProject, onAdd, onUpload = () => undefined }: {
  project: Project; docs?: Document[]; pending: PendingUpload[]; onDismiss: (key: string) => void; onProject: (project: Project) => void; onAdd: () => void; onUpload?: (files: File[]) => void
}) {
  const [error, setError] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [folder, setFolder] = useState<ProjectRole | ''>('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [editing, setEditing] = useState<ProjectDoc | null>(null)
  const input = useRef<HTMLInputElement>(null)
  async function run(id: string, action: () => Promise<Project>) {
    setBusy(id); setError('')
    try { onProject(await action()) } catch (err) { setError(err instanceof Error ? err.message : 'That change could not be saved.') } finally { setBusy(null) }
  }
  function pick(list: FileList | null) {
    const files = [...(list ?? [])]
    const bad = files.map((file) => ({ file, reason: validateUpload(file) })).find((row) => row.reason)
    setError(bad ? `${bad.file.name}: ${bad.reason}` : '')
    const good = files.filter((file) => !validateUpload(file))
    if (good.length) onUpload(good)
    if (input.current) input.current.value = ''
  }
  if (!project.docs.length && !pending.length) return <div className="pj-empty" data-testid="files-empty">
    <h2>No files yet</h2><p>Add plans, models, scans or PDFs for this building.</p>
    <Button variant="primary" onClick={onAdd}><Plus size={15} />Add files</Button>
  </div>
  const roles = projectRoles.filter((role) => project.docs.some((doc) => doc.role === role))
  const activeRole = folder && roles.includes(folder) ? folder : ''
  const visible = project.docs.filter((doc) => !activeRole || doc.role === activeRole)
  const selectedDoc = project.docs.find((doc) => doc.doc_id === selectedId)
  const ask = () => { window.location.hash = projectChatHref(project.id).slice(1) }
  const go = (role: ProjectRole | '') => { setFolder(role); setSelectedId(null) }
  return <div className="pj-files pj-explorer">
    {error && <ErrorLine message={error} />}
    <ExplorerBrowser title={activeRole ? rolePlural[activeRole] : 'All Files'} count={visible.length}
      mobileFolder={<select className="mobile-folder-select" aria-label="Document folder" value={activeRole} onChange={(event) => go(event.target.value as ProjectRole | '')}><option value="">All Files</option>{roles.map((role) => <option key={role} value={role}>{rolePlural[role]}</option>)}</select>}
      actions={<div className="pj-explorer-actions">
        <Button variant="outline" onClick={() => input.current?.click()}><Upload size={15} />Upload</Button>
        <Button variant="outline" onClick={onAdd}>Add from library</Button>
        <input ref={input} type="file" multiple hidden accept={UPLOAD_ACCEPT} aria-label="Choose files to upload" onChange={(event) => pick(event.target.files)} />
      </div>}
      nav={<>
        <FolderItem label="All Files" count={project.docs.length} current={!activeRole} icon={<Layers size={16} />} onClick={() => go('')} />
        {roles.map((role) => <FolderItem key={role} label={rolePlural[role]} count={project.docs.filter((doc) => doc.role === role).length} current={activeRole === role} onClick={() => go(role)} />)}
      </>}
      detail={selectedDoc ? <DocumentDetail key={selectedDoc.doc_id} doc={toDocument(selectedDoc, docs)} docked={false} onClose={() => setSelectedId(null)} onAsk={ask}
        actionsExtra={<Button variant="outline" onClick={() => setEditing(selectedDoc)}>Type and level</Button>} /> : null}>
      <div className="data-file-list" aria-label="Project files">
        {pending.map((row) => <article key={row.key} className="data-file-row pj-file-pending">
          <span className="data-open-file"><span className="data-thumbnail"><Upload size={18} aria-hidden="true" /></span><span><h3 title={row.name}>{row.name}</h3><small className={row.error ? 'pj-bad' : ''}>{row.error ?? 'Uploading…'}</small></span></span>
          {row.error && <Button variant="ghost" size="sm" onClick={() => onDismiss(row.key)}>Dismiss</Button>}
        </article>)}
        {visible.map((doc) => <FileRow key={doc.doc_id} doc={toDocument(doc, docs)} selected={selectedId === doc.doc_id} status={isFailed(doc) ? 'bad' : isReading(doc) ? 'busy' : undefined}
          meta={[rowMeta(doc), rowStatus(doc)].filter(Boolean).join(' · ')} onOpen={() => { if (!isReading(doc)) setSelectedId(doc.doc_id) }}
          trailing={<RowMenu doc={doc} busy={busy === doc.doc_id} onEdit={() => setEditing(doc)} onAsk={ask} onRemove={() => { if (selectedId === doc.doc_id) setSelectedId(null); void run(doc.doc_id, () => projectsApi.removeDoc(project.id, doc.doc_id)) }} />} />)}
      </div>
    </ExplorerBrowser>
    {editing && <EditFileDialog project={project} doc={editing} onClose={() => setEditing(null)} onProject={onProject} />}
  </div>
}
