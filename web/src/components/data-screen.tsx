import { useEffect, useLayoutEffect, useRef, useState, type DragEvent } from 'react'
import { ArrowRight, Box, ChevronDown, ChevronLeft, ChevronRight, Download, File, FileImage, FileText, Folder, FolderPlus, GitCompare, Info, Layers, LoaderCircle, Maximize2, MessageSquare, Minus, MoreHorizontal, PenLine, Plus, ScanText, Search, SlidersHorizontal, Upload, X } from 'lucide-react'
import { Badge, Button, Input } from './ui'
import { workspaceApi } from '../lib/api'
import type { Document, IngestStatus } from '../lib/types'
import { fitPhonePage, type Size } from '../lib/page-transform'
import { DrawingModel, ViewerModeToggle, type ViewerMode } from './drawing-model'
import './data-screen.css'
import { ShowOnTableButton } from './show-on-table'

const PAGE_SIZE = 40
const ACCEPTED = '.ifc,.dxf,.dwg,.pdf,.svg,.png,.jpg,.jpeg,.tif,.tiff'
const terminal = new Set(['ready', 'partial', 'failed', 'stored'])

type Version = { doc_id: string; index: number; date: string | null; size: number | null; label: string }
export type FileDocument = Document & {
  folder?: string; size?: number | null; updated_at?: string | null; date?: string | null
  version_count?: number | null; version_index?: number | null; versions?: Version[]
}
type FolderNode = { name: string; path: string; count: number; children: FolderNode[] }
const inFolder = (doc: FileDocument, path: string) => !path || doc.folder === path || !!doc.folder?.startsWith(`${path}/`)
function fileSize(size?: number | null) {
  if (size == null) return 'Size unavailable'
  if (size < 1024) return `${size} B`
  return size < 1024 * 1024 ? `${(size / 1024).toFixed(1)} KB` : `${(size / (1024 * 1024)).toFixed(1)} MB`
}
function fileDate(value?: string | null) {
  return value && !Number.isNaN(Date.parse(value)) ? new Date(value).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) : 'Date unavailable'
}
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

function DocumentTitle({ title }: { title: string }) {
  const suffix = title.match(/^(.*?)(\s*[—–-]?\s*generated for demo)$/i)
  return suffix ? <><span className="document-title-name">{suffix[1]}</span><small className="document-demo-label">{suffix[2]}</small></> : <span className="document-title-name">{title}</span>
}
type UploadState = {
  name: string; docId?: string; status: 'uploading' | 'stored' | IngestStatus['status']
  stages: IngestStatus['stages']; detail: string
}

function DocumentImage({ doc, preview = false, onLoad }: { doc: Document; preview?: boolean; onLoad?: (size: Size) => void }) {
  const [failed, setFailed] = useState(false)
  const Icon = doc.kind === 'ifc' || doc.kind === 'dxf' || doc.kind === 'dwg' ? Box : doc.kind === 'raster' || doc.kind === 'svg' ? FileImage : File
  return <span className={preview ? 'data-preview' : 'data-thumbnail'}>
    {!preview || failed ? <><Icon size={preview ? 56 : 18} aria-hidden="true" />{preview && <span>Page preview unavailable</span>}</> :
      <img loading="lazy" src={`/api/docs/${encodeURIComponent(doc.doc_id)}/${preview ? 'pages/1/image' : 'files/page-1.thumb.png'}`}
        alt={preview ? `First page of ${doc.title}` : ''} onError={() => setFailed(true)}
        onLoad={(event) => onLoad?.({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })} />}
  </span>
}

function FormatBadges({ doc }: { doc: Document }) {
  return <span className="data-formats">{doc.formats.map((format) => <Badge key={format}>{format.toUpperCase()}</Badge>)}</span>
}

function DocumentDetail({ doc, docked, onClose, onAsk }: { doc: Document; docked: boolean; onClose: () => void; onAsk: (doc: Document) => void }) {
  const [mode, setMode] = useState<ViewerMode>('2d')
  const [modelVisited, setModelVisited] = useState(false)
  function changeMode(next: ViewerMode) { setMode(next); if (next === '3d') setModelVisited(true) }
  const [scene, setScene] = useState<'loading' | 'available' | 'missing' | 'error'>('loading')
  const [zoom, setZoom] = useState(100)
  const [showSceneNote, setShowSceneNote] = useState(false)
  const [image, setImage] = useState<Size | null>(null)
  const [viewport, setViewport] = useState<Size>({ width: 0, height: 0 })
  const [phone, setPhone] = useState(() => window.matchMedia('(max-width: 640px)').matches)
  const canvas = useRef<HTMLDivElement>(null)
  const closeButton = useRef<HTMLButtonElement>(null)
  useLayoutEffect(() => {
    const node = canvas.current
    if (!node) return
    const query = window.matchMedia('(max-width: 640px)')
    const measure = () => {
      setPhone(query.matches)
      setViewport({ width: node.clientWidth, height: node.clientHeight })
    }
    const observer = new ResizeObserver(measure)
    observer.observe(node)
    query.addEventListener('change', measure)
    measure()
    return () => { observer.disconnect(); query.removeEventListener('change', measure) }
  }, [])
  const fitted = image && viewport.width ? fitPhonePage(image, viewport) : null
  const phoneScale = fitted ? fitted.scale * zoom / 100 : 1
  const displayedZoom = phone && fitted ? Math.round(phoneScale * 100) : zoom
  useEffect(() => {
    const controller = new AbortController()
    closeButton.current?.focus()
    workspaceApi.hasScene(doc.doc_id, controller.signal).then((available) => {
      if (!controller.signal.aborted) setScene(available ? 'available' : 'missing')
    }).catch(() => { if (!controller.signal.aborted) setScene('error') })
    return () => controller.abort()
  }, [doc.doc_id])

  return <aside className="data-detail" data-docked={docked || undefined} aria-label="Document details" onKeyDown={(event) => { if (event.key === 'Escape') { if (mode === '3d') changeMode('2d'); else onClose() } }}>
    <header><FileText size={24} /><div><h2><DocumentTitle title={doc.title} /></h2><small>/{doc.source}<span className="data-header-demo">{/generated for demo$/i.test(doc.title) ? ' · generated for demo' : ''}</span></small><details className="data-credit-info"><summary aria-label="Drawing credit and licence"><Info size={12} /></summary><div className="data-credit-popover"><dl><div><dt>Credit</dt><dd>{doc.credit || 'Not provided'}</dd></div><div><dt>Licence</dt><dd>{doc.licence || 'Not provided'}</dd></div></dl><div className="data-mobile-scene">{scene === 'available' ? <button type="button" className="viewer3d-visualise-button" onClick={() => { setShowSceneNote(false); changeMode('3d') }}>Visualise it</button> : <button type="button" disabled={scene === 'loading'} onClick={() => setShowSceneNote(true)}>Visualise it</button>}{showSceneNote && <p role="status">{scene === 'error' ? 'Could not check 3D availability. Reopen the document to retry.' : 'No 3D scene available for this document.'}</p>}</div></div></details></div>{scene === 'available' && <ViewerModeToggle mode={mode} onChange={changeMode} />}<ShowOnTableButton docId={doc.doc_id} sceneAvailable={scene === 'available'} /><button type="button" className="data-header-ask" aria-label="Ask about it" onClick={() => onAsk(doc)}><MessageSquare size={16} /></button><a className="data-compare" href="#/changes" aria-label="Compare document revisions"><GitCompare size={14} /><span>Compare</span></a><Button variant="ghost" size="icon" aria-label="Fit page" onClick={() => setZoom(100)}><Maximize2 size={16} /></Button><button ref={closeButton} type="button" className="data-close-detail" aria-label="Close document details" onClick={onClose}><X size={18} /></button></header>
    <div className="data-viewer-toolbar" hidden={mode === '3d'}><ChevronLeft size={14} /><span className="page-number">1</span><span>/ {doc.pages}</span><ChevronRight size={14} /><span className="toolbar-spacer" /><span className="data-viewer-tools" aria-hidden="true"><Search size={14} /><ScanText size={14} /><PenLine size={14} /></span><a aria-label="Download page" href={`/api/docs/${encodeURIComponent(doc.doc_id)}/pages/1/image`} download><Download size={14} /></a><span className="viewer-toolbar-divider" /><span className="data-zoom-controls"><Button variant="ghost" size="icon" aria-label="Zoom out" onClick={() => setZoom((n) => Math.max(25, n - 25))}><Minus size={14} /></Button><span aria-label="Page zoom level">{displayedZoom}%</span><Button variant="ghost" size="icon" aria-label="Zoom in" onClick={() => setZoom((n) => Math.min(400, n + 25))}><Plus size={14} /></Button></span></div>
    <div className="data-detail-body" hidden={mode === '3d'}>
      <div ref={canvas} className="data-page-canvas"><div className={`data-page-plane ${phone ? 'phone-page-plane' : ''}`} style={phone && image && fitted ? {
        width: image.width, height: image.height, transform: `translate(${(viewport.width - image.width * phoneScale) / 2}px, ${fitted.y}px) scale(${phoneScale})`,
      } : { transform: `scale(${zoom / 100})` }}><DocumentImage key={doc.doc_id} doc={doc} preview onLoad={setImage} /></div></div>
      <dl className="data-document-credit"><div><dt>Credit</dt><dd>{doc.credit || 'Not provided'}</dd></div><div><dt>Licence</dt><dd>{doc.licence || 'Not provided'}</dd></div></dl>
      <div className="data-detail-actions"><Button variant="raised" onClick={() => onAsk(doc)}>Ask about it<ArrowRight size={15} /></Button>
        {scene === 'available' && <button type="button" className="viewer3d-visualise-button" onClick={() => { setShowSceneNote(false); changeMode('3d') }}>Visualise it</button>}</div>
      <p className="data-scene-note" role="status">{scene === 'loading' ? 'Checking for a 3D scene…' : scene === 'missing' ? 'No 3D scene available for this document.' : scene === 'error' ? 'Could not check 3D availability. Reopen the document to retry.' : '3D scene available.'}</p>
    </div>
    {modelVisited && <div className="viewer-model-slot" hidden={mode !== '3d'}><DrawingModel docId={doc.doc_id} /></div>}
  </aside>
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
  const openedUpload = useRef<string | null>(null)
  useEffect(() => {
    if (demo || hidden) return
    const controller = new AbortController()
    setFolderLoading(true)
    setFolderError('')
    fetch('/api/folders', { signal: controller.signal }).then(async (response) => {
      if (!response.ok) throw new Error(`Could not load folders (${response.status}).`)
      const result = await response.json() as { folders: FolderNode[] }
      if (!controller.signal.aborted) setFolders(result.folders)
    }).catch((error: unknown) => { if (!controller.signal.aborted) setFolderError(error instanceof Error ? error.message : 'Could not load folders.') })
      .finally(() => { if (!controller.signal.aborted) setFolderLoading(false) })
    return () => controller.abort()
  }, [demo, hidden, docs, folderRetry])
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [previewDocked, setPreviewDocked] = useState(false)
  const [upload, setUpload] = useState<UploadState | null>(null)
  const [uploadError, setUploadError] = useState('')
  const [pollAttempt, setPollAttempt] = useState(0)
  const [dragging, setDragging] = useState(false)
  const uploadInput = useRef<HTMLInputElement>(null)
  const uploading = useRef(false)
  const lastOpened = useRef<HTMLButtonElement | null>(null)
  const pending = !!upload && !terminal.has(upload.status)

  // Reopening Data keeps the retained preview alongside navigation. Opening a
  // file explicitly starts a full-screen reading session on phones.
  useLayoutEffect(() => {
    if (hidden && selectedId) setPreviewDocked(true)
  }, [hidden, selectedId])

  useEffect(() => {
    if (!upload?.docId || terminal.has(upload.status)) return
    const docId = upload.docId
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    async function poll() {
      try {
        const result = await workspaceApi.getIngestStatus(docId, controller.signal)
        if (controller.signal.aborted) return
        setUpload((previous) => previous ? { ...previous, ...result } : previous)
        if (terminal.has(result.status)) {
          await onRefresh()
          if (controller.signal.aborted) return
          if (result.status === 'ready' || result.status === 'partial') {
            setOlderDoc(null)
            setPreviewDocked(false)
            setSelectedId(docId)
            openedUpload.current = docId
          }
        } else {
          timer = setTimeout(poll, 1500)
        }
      } catch (error) {
        if (!controller.signal.aborted) setUploadError(error instanceof Error ? error.message : 'Could not check upload progress.')
      }
    }
    void poll()
    return () => { controller.abort(); clearTimeout(timer) }
    // Status updates must not restart the poll; only a new upload or an explicit retry does.
  }, [upload?.docId, pollAttempt, onRefresh])

  async function uploadFile(file: File) {
    if (uploading.current || pending) return
    setUploadError('')
    if (!/\.(ifc|dxf|dwg|pdf|svg|png|jpe?g|tiff?)$/i.test(file.name)) {
      setUploadError('Choose an IFC, DXF, DWG, PDF, SVG, PNG, JPG or TIF file.')
      return
    }
    if (file.size > 100 * 1024 * 1024) { setUploadError('Choose a file smaller than 100 MB.'); return }
    uploading.current = true
    setUpload({ name: file.name, status: 'uploading', detail: '', stages: [] })
    try {
      const receipt = await workspaceApi.uploadDocument(file)
      setUpload({ name: file.name, docId: receipt.doc_id, status: receipt.status === 'stored' ? 'stored' : 'running', detail: receipt.status === 'stored' ? receipt.detail : '', stages: [] })
      setFolder('Uploads')
      setSearch('')
      setPage(1)
      await onRefresh()
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : 'Upload failed. Please try again.')
      setUpload((previous) => previous?.docId ? previous : null)
    } finally {
      uploading.current = false
    }
  }

  function drop(event: DragEvent) {
    event.preventDefault()
    setDragging(false)
    if (event.dataTransfer.files[0]) void uploadFile(event.dataTransfer.files[0])
  }

  function closeDetail() {
    setSelectedId(null)
    requestAnimationFrame(() => lastOpened.current?.focus())
  }

  useEffect(() => {
    if (!upload?.docId || upload.status !== 'stored' || openedUpload.current === upload.docId || !docs.some((doc) => doc.doc_id === upload.docId)) return
    openedUpload.current = upload.docId
    setOlderDoc(null)
    setPreviewDocked(false)
    setSelectedId(upload.docId)
  }, [docs, upload])

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
  const filtered = docs.filter((doc) => query ? `${doc.title} ${doc.doc_id} ${doc.source} ${doc.folder || ''} ${doc.formats.join(' ')} ${doc.licence || ''} ${doc.credit || ''}`.toLowerCase().includes(query) : inFolder(doc, activeFolder))
  if (upload?.docId) filtered.sort((a, b) => Number(b.doc_id === upload.docId) - Number(a.doc_id === upload.docId))
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const currentPage = Math.min(page, pageCount)
  const visible = filtered.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE)
  const selected = docs.find((doc) => doc.doc_id === selectedId) || (olderDoc?.doc_id === selectedId ? olderDoc : null)
  const uploadLabel = !upload ? '' : upload.status === 'uploading' ? 'Uploading…' : upload.status === 'running' || upload.status === 'none' ? 'Processing document…' : upload.status === 'ready' ? 'Ready to use' : upload.status === 'partial' ? 'Page preview ready; some processing is unavailable.' : upload.status === 'failed' ? 'Processing failed. The original file is stored.' : 'File stored. Processing is unavailable on this server.'

  return <section className="data-screen" aria-label="Project documents" hidden={hidden} onDragOver={(event) => {
    event.preventDefault()
    if (!demo && !pending) setDragging(true)
  }} onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false) }} onDrop={(event) => {
    if (demo || pending) { event.preventDefault(); setDragging(false) } else drop(event)
  }}>
    <div className="data-screen-toolbar"><div><h2>Project documents</h2><p>The sources behind your answers.</p></div>
      <Button variant="raised" disabled={demo || pending} onClick={() => uploadInput.current?.click()}><Upload size={16} />Upload</Button>
    </div>
    <input ref={uploadInput} className="data-file-input" type="file" aria-label="Upload drawing" accept={ACCEPTED} disabled={demo || pending} onChange={(event) => {
      const file = event.target.files?.[0]
      event.target.value = ''
      if (file) void uploadFile(file)
    }} />
    <div className={`data-drop-zone ${dragging ? 'is-dragging' : ''}`}>
      <Upload size={18} aria-hidden="true" /><span>{demo ? 'Connect to the server to upload a drawing.' : 'Drop a drawing here, or use Upload.'}<small>One file at a time · IFC, DXF, DWG, PDF, SVG, PNG, JPG, TIF · up to 100 MB</small></span>
    </div>
    {upload && <div className="data-upload-status" role="status" aria-live="polite" aria-busy={pending && !uploadError}>
      {pending && !uploadError && <LoaderCircle size={16} className="data-spinner" />}<div><strong>{upload.name}</strong><p>{uploadLabel}</p>{pending && <progress aria-label="Document processing" />} {upload.detail && !terminal.has(upload.status) && <p>{upload.detail}</p>}
        {!!upload.stages.length && <ul>{upload.stages.map((stage, index) => <li key={`${stage.stage}-${index}`}>{stage.stage}: {stage.ok ? 'complete' : 'unavailable'}</li>)}</ul>}
        {upload.detail && terminal.has(upload.status) && <p>{upload.detail}</p>}</div>
    </div>}
    {uploadError && <div className="data-upload-error"><p role="alert">{uploadError}</p>{upload?.docId && <Button variant="outline" onClick={async () => {
      setUploadError('')
      setPollAttempt((attempt) => attempt + 1)
      try { await onRefresh() } catch (error) { setUploadError(error instanceof Error ? error.message : 'Could not refresh documents.') }
    }}>Retry status</Button>}</div>}
    {versionError && <p className="data-upload-error" role="alert">{versionError}</p>}
    <div className={`data-browser ${selected ? 'has-detail' : ''}`}>
      <nav className="data-folders" aria-label="Document folders"><h2>Folders<FolderPlus size={14} /></h2>
        <button className="all-files" type="button" aria-current={!activeFolder && !query ? 'page' : undefined} onClick={() => { setFolder(''); setSearch(''); setPage(1) }}><Layers size={16} /><span>All Files</span><small>{docs.length}</small></button>
        {folderLoading && <p role="status" className="data-folder-message">Loading folders…</p>}
        {folderError && <div className="data-folder-message"><p role="alert">{folderError}</p><button type="button" onClick={() => setFolderRetry((n) => n + 1)}>Retry folders</button></div>}
        {folders.map((node) => <FolderBranch key={node.path} node={node} active={query ? '' : activeFolder} onSelect={(path) => { setFolder(path); setSearch(''); setPage(1) }} />)}
      </nav>
      <label className={`data-folder-search ${search ? 'has-query' : ''}`}><Search size={16} /><Input type="search" aria-label="Search documents" placeholder="Search all documents" value={search} onChange={(event) => { setSearch(event.target.value); setPage(1) }} /></label>
      <div className="data-files"><header><h2>{query ? 'Search results · all folders' : activeFolder || 'All Files'}</h2><ChevronLeft className="mobile-folder-back" size={14} /><select className="mobile-folder-select" aria-label="Document folder" value={activeFolder} onChange={(event) => { setFolder(event.target.value); setSearch(''); setPage(1) }}><option value="">All Files</option>{options.map((option) => <option key={option.path} value={option.path}>{option.label}</option>)}</select><SlidersHorizontal className="mobile-folder-filter" size={14} /><span>Files ({filtered.length})</span></header>
        {loading ? <p className="data-empty" role="status">Loading documents…</p> : !visible.length ? <p className="data-empty">No documents found.</p> : <div className="data-file-list">{visible.map((doc) => <article key={doc.doc_id} className="data-file-row" data-doc-id={doc.doc_id} data-selected={selectedId === doc.doc_id || undefined}>
          <button className="data-open-file" type="button" aria-label={`Open ${doc.title}`} aria-expanded={selectedId === doc.doc_id} onClick={(event) => { lastOpened.current = event.currentTarget; setPreviewDocked(false); setSelectedId(doc.doc_id) }}>
            <span className="file-checkbox" aria-hidden="true" /><DocumentImage key={doc.doc_id} doc={doc} /><span><h3><DocumentTitle title={doc.title} /></h3><span className="data-file-meta">{doc.folder || doc.source} · {doc.pages} {doc.pages === 1 ? 'page' : 'pages'}</span><small>{doc.licence || 'Licence not provided'} · {doc.credit || 'Credit not provided'}</small></span>
          </button><div className="data-file-facts"><span aria-label="File size">{fileSize(doc.size)}</span><time aria-label="File date" dateTime={doc.date || doc.updated_at || undefined}>{fileDate(doc.date || doc.updated_at)}</time>
            {doc.versions?.length ? <label className="data-version-picker"><span>{doc.version_count ?? doc.versions.length} versions</span><select aria-label={`Versions of ${doc.title}`} value={doc.versions.some((version) => version.doc_id === selectedId) ? selectedId! : doc.doc_id} disabled={versionLoading} onChange={(event) => void openVersion(event.target.value)}>{doc.versions.map((version) => <option key={version.doc_id} value={version.doc_id}>{version.label}</option>)}</select></label> : <span>{doc.version_count == null ? 'Version count unavailable' : `${doc.version_count} ${doc.version_count === 1 ? 'version' : 'versions'}`}</span>}
          </div><FormatBadges doc={doc} /><MoreHorizontal className="file-row-more" size={16} />
        </article>)}</div>}
        {!loading && filtered.length > 0 && <div className="data-pagination" aria-label="Document pagination"><span>{(currentPage - 1) * PAGE_SIZE + 1}–{Math.min(currentPage * PAGE_SIZE, filtered.length)} of {filtered.length}</span>
          <Button variant="ghost" size="icon" aria-label="Previous document page" disabled={currentPage === 1} onClick={() => setPage(currentPage - 1)}><ChevronLeft size={17} /></Button>
          <span>Page {currentPage} of {pageCount}</span><Button variant="ghost" size="icon" aria-label="Next document page" disabled={currentPage === pageCount} onClick={() => setPage(currentPage + 1)}><ChevronRight size={17} /></Button></div>}
      </div>
      {selected && <DocumentDetail key={selected.doc_id} doc={selected} docked={previewDocked} onClose={closeDetail} onAsk={onAsk} />}
    </div>
  </section>
}
