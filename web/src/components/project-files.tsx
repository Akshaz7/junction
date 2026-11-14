import { useCallback, useEffect, useRef, useState } from 'react'
import { Plus, X } from 'lucide-react'
import { Button } from './ui'
import { emptyChoice, ErrorLine, FilesChooser, hasChoice, ProjectDialog, TypeTag, type FileChoice } from './project-parts'
import { projectRoles, projectsApi, takeUploads, type Project, type ProjectDoc, type ProjectRole } from '../lib/projects-api'
import { docTitle, isFailed, isReading, roleLabels } from '../lib/projects-format'
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

function LevelField({ doc, disabled, onCommit }: { doc: ProjectDoc; disabled: boolean; onCommit: (level: string | null) => void }) {
  const [value, setValue] = useState(doc.level ?? '')
  useEffect(() => setValue(doc.level ?? ''), [doc.level])
  const commit = () => { const next = value.trim() || null; if (next !== (doc.level ?? null)) onCommit(next) }
  return <input className="pj-cell-input" value={value} disabled={disabled} placeholder="Level" aria-label={`Level for ${docTitle(doc)}`} maxLength={60}
    onChange={(event) => setValue(event.target.value)} onBlur={commit} onKeyDown={(event) => { if (event.key === 'Enter') event.currentTarget.blur() }} />
}

export function FilesTab({ project, pending, onDismiss, onProject, onAdd }: { project: Project; pending: PendingUpload[]; onDismiss: (key: string) => void; onProject: (project: Project) => void; onAdd: () => void }) {
  const [error, setError] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  async function run(id: string, action: () => Promise<Project>) {
    setBusy(id); setError('')
    try { onProject(await action()) } catch (err) { setError(err instanceof Error ? err.message : 'That change could not be saved.') } finally { setBusy(null) }
  }
  if (!project.docs.length && !pending.length) return <div className="pj-empty" data-testid="files-empty">
    <h2>No files yet</h2><p>Add plans, models, scans or PDFs for this building.</p>
    <Button variant="primary" onClick={onAdd}><Plus size={15} />Add files</Button>
  </div>
  return <div className="pj-files">
    {error && <ErrorLine message={error} />}
    <div className="pj-files-head" aria-hidden="true"><span>File</span><span>Type</span><span>Level</span><span /></div>
    <ul aria-label="Project files">
      {pending.map((row) => <li key={row.key} className="pj-file pj-file-pending">
        <div className="pj-file-name"><span className="pj-tag">{row.name.split('.').pop()?.toUpperCase() || 'FILE'}</span><span><strong>{row.name}</strong><small className={row.error ? 'pj-bad' : ''}>{row.error ?? 'Uploading…'}</small></span></div>
        {row.error && <Button variant="ghost" size="sm" onClick={() => onDismiss(row.key)}>Dismiss</Button>}
      </li>)}
      {project.docs.map((doc) => <li key={doc.doc_id} className="pj-file" data-doc-id={doc.doc_id}>
        <div className="pj-file-name"><TypeTag doc={doc} /><span><strong>{docTitle(doc)}</strong>
          <small className={isFailed(doc) ? 'pj-bad' : ''}>{isFailed(doc) ? 'Could not be read' : isReading(doc) ? 'Reading the file…' : doc.role_source === 'user' ? 'Set by you' : 'Set automatically'}</small></span></div>
        <select className="pj-cell-input" aria-label={`Type of ${docTitle(doc)}`} value={doc.role} disabled={busy === doc.doc_id} onChange={(event) => void run(doc.doc_id, () => projectsApi.updateDoc(project.id, doc.doc_id, { role: event.target.value as ProjectRole }))}>
          {projectRoles.map((role) => <option key={role} value={role}>{roleLabels[role]}</option>)}
        </select>
        <LevelField doc={doc} disabled={busy === doc.doc_id} onCommit={(level) => void run(doc.doc_id, () => projectsApi.updateDoc(project.id, doc.doc_id, { level }))} />
        <Button variant="ghost" size="icon-sm" aria-label={`Remove ${docTitle(doc)} from project`} disabled={busy === doc.doc_id} onClick={() => void run(doc.doc_id, () => projectsApi.removeDoc(project.id, doc.doc_id))}><X size={15} /></Button>
      </li>)}
    </ul>
  </div>
}
