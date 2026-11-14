import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Check, FileText, Search, Upload, X } from 'lucide-react'
import { Button } from './ui'
import { searchDocuments } from '../lib/doc-search'
import { UPLOAD_ACCEPT, validateUpload } from '../lib/upload-state'
import { docTitle, typeTag } from '../lib/projects-format'
import type { Document } from '../lib/types'
import './project.css'

export function TypeTag({ doc }: { doc: { kind: string; formats: string[] } }) {
  return <span className="pj-tag">{typeTag(doc)}</span>
}

export function Skeleton({ lines = 3, className = '' }: { lines?: number; className?: string }) {
  return <div className={`pj-skeleton ${className}`} aria-hidden="true">{Array.from({ length: lines }, (_, index) => <span key={index} className="skeleton-line" style={{ width: `${[62, 88, 74, 54][index % 4]}%` }} />)}</div>
}

export function ErrorLine({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return <p className="pj-error" role="alert">{message}{onRetry && <> <button type="button" onClick={onRetry}>Try again</button></>}</p>
}

/** A modal in the app's dialog style. */
export function ProjectDialog({ title, description, onClose, children, footer }: { title: string; description?: string; onClose: () => void; children: ReactNode; footer: ReactNode }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const titleId = useId()
  useEffect(() => {
    const element = dialog.current!
    const previous = document.activeElement
    element.showModal()
    return () => { element.close(); if (previous instanceof HTMLElement && previous.isConnected) previous.focus() }
  }, [])
  return createPortal(<dialog ref={dialog} className="pj-dialog" aria-labelledby={titleId} onCancel={(event) => { event.preventDefault(); onClose() }}>
    <header><div><h2 id={titleId}>{title}</h2>{description && <p>{description}</p>}</div><Button variant="ghost" size="icon" aria-label="Close" onClick={onClose}><X size={16} /></Button></header>
    <div className="pj-dialog-body">{children}</div>
    <footer>{footer}</footer>
  </dialog>, document.body)
}

export type FileChoice = { libraryIds: string[]; files: File[] }
export const emptyChoice: FileChoice = { libraryIds: [], files: [] }
export const hasChoice = (choice: FileChoice) => choice.libraryIds.length + choice.files.length > 0

/** Pick files from the library or from this computer. Any file the app accepts. */
export function FilesChooser({ docs, taken = [], value, onChange }: { docs: Document[]; taken?: string[]; value: FileChoice; onChange: (value: FileChoice) => void }) {
  const [library, setLibrary] = useState(false)
  const [query, setQuery] = useState('')
  const [problem, setProblem] = useState('')
  const input = useRef<HTMLInputElement>(null)
  const available = docs.filter((doc) => !taken.includes(doc.doc_id))
  const shown = query.trim() ? searchDocuments(available, query) : available
  const toggle = (id: string) => onChange({ ...value, libraryIds: value.libraryIds.includes(id) ? value.libraryIds.filter((item) => item !== id) : [...value.libraryIds, id] })
  function pick(list: FileList | null) {
    const files = [...(list ?? [])]
    const bad = files.map((file) => ({ file, reason: validateUpload(file) })).find((row) => row.reason)
    setProblem(bad ? `${bad.file.name}: ${bad.reason}` : '')
    const good = files.filter((file) => !validateUpload(file) && !value.files.some((old) => old.name === file.name && old.size === file.size))
    if (good.length) onChange({ ...value, files: [...value.files, ...good] })
    if (input.current) input.current.value = ''
  }
  return <div className="pj-chooser">
    <div className="pj-chooser-actions">
      <Button variant="outline" onClick={() => input.current?.click()}><Upload size={15} />Upload files</Button>
      <Button variant="outline" aria-expanded={library} onClick={() => setLibrary((open) => !open)} disabled={!available.length}>Add from library</Button>
      <input ref={input} type="file" multiple hidden accept={UPLOAD_ACCEPT} aria-label="Choose files to upload" onChange={(event) => pick(event.target.files)} />
    </div>
    <p className="pj-hint">PNG, JPG, IFC, DXF or PDF, up to 100 MiB each.</p>
    {problem && <p className="pj-error" role="alert">{problem}</p>}
    {library && <div className="pj-picker">
      <label className="pj-search"><Search size={15} aria-hidden="true" /><input type="search" placeholder="Search the library" aria-label="Search the library" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
      <ul role="listbox" aria-label="Library documents" aria-multiselectable="true">{shown.map((doc) => {
        const on = value.libraryIds.includes(doc.doc_id)
        return <li key={doc.doc_id}><button type="button" role="option" aria-selected={on} className={on ? 'on' : ''} onClick={() => toggle(doc.doc_id)}>
          <span className="pj-check" aria-hidden="true">{on && <Check size={12} />}</span><span className="pj-pick-title">{docTitle(doc)}</span><TypeTag doc={doc} />
        </button></li>
      })}</ul>
      {!shown.length && <p className="pj-hint pj-pad">No matching documents.</p>}
    </div>}
    {hasChoice(value) && <ul className="pj-chosen" aria-label="Files to add">
      {value.libraryIds.map((id) => { const doc = docs.find((item) => item.doc_id === id); return <li key={id}><FileText size={14} /><span>{doc ? docTitle(doc) : id}</span><button type="button" aria-label={`Remove ${doc ? docTitle(doc) : id}`} onClick={() => toggle(id)}><X size={14} /></button></li> })}
      {value.files.map((file) => <li key={`${file.name}-${file.size}`}><Upload size={14} /><span>{file.name}</span><button type="button" aria-label={`Remove ${file.name}`} onClick={() => onChange({ ...value, files: value.files.filter((item) => item !== file) })}><X size={14} /></button></li>)}
    </ul>}
  </div>
}
