import { searchDocuments } from '../lib/doc-search'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { ChevronDown, ChevronLeft, ChevronRight, File, Folder, Layers, Search, Upload } from 'lucide-react'
import { Button, Input } from './ui'
import { DocumentDetail, ExplorerBrowser, FileRow, fileDate, fileSize } from './file-explorer'
import { workspaceApi } from '../lib/api'
import type { Document } from '../lib/types'
import './data-screen.css'
import { UploadDialog } from './upload-dialog'
import { ConnectionPill } from './connection-pill'

const PAGE_SIZE = 40

type Version = { doc_id: string; index: number; date: string | null; size: number | null; label: string }
export type FileDocument = Document & {
  folder?: string; size?: number | null; updated_at?: string | null; date?: string | null
  version_count?: number | null; version_index?: number | null; versions?: Version[]
}
type FolderNode = { name: string; path: string; count: number; children: FolderNode[] }
const titleKey = (doc: FileDocument) => doc.title.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()
/** Stable: keeps the server order between different titles; same-title copies newest (updated_at) first. */
function newestCopyFirst(rows: FileDocument[]): FileDocument[] {
  const first = new Map<string, number>()
  rows.forEach((doc, i) => { if (!first.has(titleKey(doc))) first.set(titleKey(doc), i) })
  const time = (doc: FileDocument) => Date.parse(doc.updated_at ?? '') || 0
  return rows.map((doc, i) => ({ doc, i })).sort((a, b) => first.get(titleKey(a.doc))! - first.get(titleKey(b.doc))!
    || time(b.doc) - time(a.doc) || a.i - b.i).map((row) => row.doc)
}
const inFolder = (doc: FileDocument, path: string) => !path || doc.folder === path || !!doc.folder?.startsWith(`${path}/`)
function FolderBranch({ node, active, onSelect }: { node: FolderNode; active: string; onSelect: (path: string) => void }) {
  const [expanded, setExpanded] = useState(false)
  const open = expanded || active === node.path || active.startsWith(`${node.path}/`)
  return <div className="data-folder-branch">
    <div className="data-folder-line">{node.children.length > 0 && <button className="data-folder-expand" type="button" aria-label={`${open ? 'Collapse' : 'Expand'} ${node.path}`} aria-expanded={open} onClick={() => { if (open && active.startsWith(node.path)) onSelect(''); setExpanded(!open) }}>{open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}</button>}
      <button type="button" aria-label={`Open ${node.path} folder`} aria-current={active === node.path ? 'page' : undefined} onClick={() => { onSelect(node.path); setExpanded(true) }}><Folder size={14} /><span>{node.name}</span><small>{node.count}</small></button></div>
    {open && node.children.length > 0 && <div className="data-folder-children">{node.children.map((child) => <FolderBranch key={child.path} node={child} active={active} onSelect={onSelect} />)}</div>}
  </div>
}
function folderOptions(nodes: FolderNode[], depth = 0): { path: string; label: string }[] {
  return nodes.flatMap((node) => [{ path: node.path, label: `${' '.repeat(depth)}${node.name}` }, ...folderOptions(node.children, depth + 1)])
}

export function DataScreen({ docs, loading, demo, hidden, onRefresh, onAsk }: {
  docs: FileDocument[]; loading: boolean; demo: boolean; hidden: boolean
  onRefresh: () => Promise<void>; onAsk: (doc: Document) => void
}) {
  const [folder, setFolder] = useState('')
  const [folders, setFolders] = useState<FolderNode[]>([])
  const [folderError, setFolderError] = useState('')
  const [folderLoading, setFolderLoading] = useState(true)
  const [folderRetry, setFolderRetry] = useState(0)
  const [olderDoc, setOlderDoc] = useState<FileDocument | null>(null)
  const [versionError, setVersionError] = useState('')
  const [versionLoading, setVersionLoading] = useState(false)
  const versionRequest = useRef(0)
  const haveFolders = useRef(false)
  useEffect(() => {
    if (demo || hidden) return
    const controller = new AbortController()
    // Background refreshes (upload polling) keep the current tree on screen instead of flashing "Loading folders…".
    if (!haveFolders.current) setFolderLoading(true)
    setFolderError('')
    fetch('/api/folders', { signal: controller.signal }).then(async (response) => {
      if (!response.ok) throw new Error(`Could not load folders (${response.status}).`)
      const result = await response.json() as { folders: FolderNode[] }
      if (!controller.signal.aborted) { setFolders(result.folders); haveFolders.current = true }
    }).catch((error: unknown) => { if (!controller.signal.aborted) setFolderError(error instanceof Error ? error.message : 'Could not load folders.') })
      .finally(() => { if (!controller.signal.aborted) setFolderLoading(false) })
    return () => controller.abort()
  }, [demo, hidden, docs, folderRetry])
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [newId, setNewId] = useState<string | null>(null)
  const [previewDocked, setPreviewDocked] = useState(false)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const lastOpened = useRef<HTMLButtonElement | null>(null)
  const uploadPoll = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearInterval(uploadPoll.current), [])

  function openUpload() { setUploadError(''); setUploadOpen(true) }
  useEffect(() => { // chat's "Upload" note lands here with the dialog already open (the screen may stay mounted)
    function check() {
      try { if (window.location.hash.startsWith('#/data') && sessionStorage.getItem('hologram.open-upload')) { sessionStorage.removeItem('hologram.open-upload'); setUploadError(''); setUploadOpen(true) } } catch { /* optional */ }
    }
    check()
    window.addEventListener('hashchange', check)
    return () => window.removeEventListener('hashchange', check)
  }, [])

  useEffect(() => {
    function followUploadLink() {
      if (hidden || demo || new URLSearchParams(window.location.hash.split('?')[1]).get('upload') !== '1') return
      openUpload()
      window.history.replaceState(window.history.state, '', '#/data')
    }
    followUploadLink()
    window.addEventListener('hashchange', followUploadLink)
    return () => window.removeEventListener('hashchange', followUploadLink)
  }, [hidden, demo])

  // Reopening Data keeps the retained preview alongside navigation. Opening a
  // file explicitly starts a full-screen reading session on phones.
  useLayoutEffect(() => {
    if (hidden && selectedId) setPreviewDocked(true)
  }, [hidden, selectedId])

  function closeDetail() {
    setSelectedId(null)
    requestAnimationFrame(() => lastOpened.current?.focus())
  }

  async function openVersion(id: string) {
    const request = ++versionRequest.current
    setVersionError('')
    const existing = docs.find((doc) => doc.doc_id === id)
    if (existing) { setVersionLoading(false); setSelectedId(id); setOlderDoc(null); setPreviewDocked(false); return }
    setVersionLoading(true)
    try {
      const doc = await workspaceApi.getDocument(id)
      if (request !== versionRequest.current) return
      setOlderDoc(doc); setSelectedId(id); setPreviewDocked(false)
    } catch (error) {
      if (request !== versionRequest.current) return
      // Older revisions are not always in the document catalogue; their page images still are.
      const latest = docs.find((doc) => doc.versions?.some((version) => version.doc_id === id))
      const version = latest?.versions?.find((item) => item.doc_id === id)
      if (latest && version) { setOlderDoc({ ...latest, doc_id: id, title: `${latest.title} (${version.label})` }); setSelectedId(id); setPreviewDocked(false) }
      else setVersionError(error instanceof Error ? error.message : 'Could not open this version.')
    }
    finally { if (request === versionRequest.current) setVersionLoading(false) }
  }

  const activeFolder = folder
  const options = folderOptions(folders)
  const query = search.trim().toLowerCase()
  // Searching always spans every source, even with a folder selected.
  // Re-uploads of one file keep its title (only case/separators may differ): list the newest copy first so the
  // first row is the latest ingest, not a stale copy built by an older pipeline.
  const filtered = query ? searchDocuments(docs, query) : newestCopyFirst(docs.filter((doc) => inFolder(doc, activeFolder)))
  if (newId && !query) { const at = filtered.findIndex((doc) => doc.doc_id === newId); if (at > 0) filtered.unshift(...filtered.splice(at, 1)) }
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const currentPage = Math.min(page, pageCount)
  const visible = filtered.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE)
  const selected = docs.find((doc) => doc.doc_id === selectedId) || (olderDoc?.doc_id === selectedId ? olderDoc : null)
  return <><ConnectionPill enabled={!demo} /><section className="data-screen" aria-label="Project documents" hidden={hidden}>
    <div className="data-screen-toolbar"><div><h2>Project documents</h2><p>The sources behind your answers.</p></div>
      <Button variant="raised" disabled={demo} onClick={openUpload}><Upload size={16} />Upload</Button>
    </div>
    <UploadDialog open={uploadOpen} onClose={() => setUploadOpen(false)} onAsk={onAsk}
      onOpen={(doc) => { setOlderDoc(doc); setPreviewDocked(false); setSelectedId(doc.doc_id) }}
      onUploaded={(docId) => {
        setNewId(docId); setSelectedId(docId)
        // The dialog may be closed during processing: keep refreshing so the new document appears without a reload.
        setFolder(''); setSearch(''); setPage(1)
        // One poll per screen: a later upload replaces it rather than stacking another 2-minute timer.
        window.clearInterval(uploadPoll.current)
        let tries = 0
        uploadPoll.current = window.setInterval(() => { void onRefresh().catch(() => undefined); if (++tries >= 24) window.clearInterval(uploadPoll.current) }, 5000)
        void onRefresh().catch(() => undefined)
      }}
      onReady={() => {
        setFolder(''); setSearch(''); setPage(1)
        void onRefresh().catch((error: unknown) => setUploadError(error instanceof Error ? error.message : 'Could not refresh documents.'))
      }} />
    <div className="data-drop-zone">
      <Upload size={18} aria-hidden="true" /><span>{demo ? 'Connect to the server to upload a drawing.' : 'Use Upload to choose or drop a drawing.'}<small>One file at a time · PDF, PNG, JPG, DXF, IFC · up to 100 MiB</small></span>
    </div>
    {uploadError && <div className="data-upload-error"><p role="alert">{uploadError}</p><Button variant="outline" onClick={async () => {
      setUploadError('')
      try { await onRefresh() } catch (error) { setUploadError(error instanceof Error ? error.message : 'Could not refresh documents.') }
    }}>Retry refresh</Button></div>}
    {versionError && <p className="data-upload-error" role="alert">{versionError}</p>}
    <ExplorerBrowser detail={selected ? <DocumentDetail key={selected.doc_id} doc={selected} docked={previewDocked} onClose={closeDetail} onAsk={onAsk} /> : null}
      title={query ? 'Search results · all folders' : activeFolder || 'All Files'} count={filtered.length} mobileFolder={<select className="mobile-folder-select" aria-label="Document folder" value={activeFolder} onChange={(event) => { setFolder(event.target.value); setSearch(''); setPage(1); setSelectedId(null) }}><option value="">All Files</option>{options.map((option) => <option key={option.path} value={option.path}>{option.label}</option>)}</select>}
      search={<label className={`data-folder-search ${search ? 'has-query' : ''}`}><Search size={16} /><Input type="search" aria-label="Search documents" placeholder="Search all documents" value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); setSelectedId(null) }} /></label>}
      nav={<>
        <button className="all-files" type="button" aria-current={!activeFolder && !query ? 'page' : undefined} onClick={() => { setFolder(''); setSearch(''); setPage(1); setSelectedId(null) }}><Layers size={16} /><span>All Files</span><small>{docs.length}</small></button>
        {folderLoading && <p role="status" className="data-folder-message">Loading folders…</p>}
        {folderError && <div className="data-folder-message"><p role="alert">{folderError}</p><button type="button" onClick={() => setFolderRetry((n) => n + 1)}>Retry folders</button></div>}
        {folders.map((node) => <FolderBranch key={node.path} node={node} active={query ? '' : activeFolder} onSelect={(path) => { setFolder(path); setSearch(''); setPage(1); setSelectedId(null) }} />)}
      </>}>
        {loading ? <p className="data-empty" role="status">Loading documents…</p> : !visible.length ? <div className="data-empty"><p>{query ? 'No documents match' : 'No documents yet.'}</p><div className="data-empty-actions">{(query || activeFolder) && <Button variant="outline" onClick={() => { setSearch(''); setFolder(''); setPage(1) }}>{query ? 'Clear search' : 'All files'}</Button>}<Button variant="raised" disabled={demo} onClick={openUpload}>Upload</Button></div></div> :<div className="data-file-list">{visible.map((doc) => <FileRow key={doc.doc_id} doc={doc} selected={selectedId === doc.doc_id}
          meta={<>{doc.folder || doc.source} · {doc.pages} {doc.pages === 1 ? 'page' : 'pages'}</>} sub={<>{doc.licence || 'Licence not provided'} · {doc.credit || 'Credit not provided'}</>}
          onOpen={(button) => { lastOpened.current = button as HTMLButtonElement; setPreviewDocked(false); setSelectedId(doc.doc_id) }}
          facts={<>{fileSize(doc.size) !== null && <span aria-label="File size">{fileSize(doc.size)}</span>}{fileDate(doc.date || doc.updated_at) && <time aria-label="File date" dateTime={doc.date || doc.updated_at || undefined}>{fileDate(doc.date || doc.updated_at)}</time>}
            {doc.versions?.length ? <label className="data-version-picker"><span>{doc.version_count ?? doc.versions.length} versions</span><select aria-label={`Versions of ${doc.title}`} value={doc.versions.some((version) => version.doc_id === selectedId) ? selectedId! : doc.doc_id} disabled={versionLoading} onChange={(event) => void openVersion(event.target.value)}>{doc.versions.map((version) => <option key={version.doc_id} value={version.doc_id}>{version.label}</option>)}</select></label> : doc.version_count != null && Number.isFinite(doc.version_count) && <span>{doc.version_count} {doc.version_count === 1 ? 'version' : 'versions'}</span>}</>} />)}</div>}
        {!loading && filtered.length > 0 && <div className="data-pagination" aria-label="Document pagination"><span>{(currentPage - 1) * PAGE_SIZE + 1}–{Math.min(currentPage * PAGE_SIZE, filtered.length)} of {filtered.length}</span>
          <Button variant="ghost" size="icon" aria-label="Previous document page" disabled={currentPage === 1} onClick={() => setPage(currentPage - 1)}><ChevronLeft size={17} /></Button>
          <span>Page {currentPage} of {pageCount}</span><Button variant="ghost" size="icon" aria-label="Next document page" disabled={currentPage === pageCount} onClick={() => setPage(currentPage + 1)}><ChevronRight size={17} /></Button></div>}
    </ExplorerBrowser>
  </section></>
}
