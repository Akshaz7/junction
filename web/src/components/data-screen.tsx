import { useEffect, useLayoutEffect, useRef, useState, type DragEvent } from 'react'
import { ArrowRight, Box, ChevronDown, ChevronLeft, ChevronRight, Download, File, FileImage, FileText, Folder, FolderPlus, GitCompare, Info, Layers, LoaderCircle, Maximize2, MessageSquare, Minus, MoreHorizontal, PenLine, Plus, ScanText, Search, SlidersHorizontal, Upload, X } from 'lucide-react'
import { Badge, Button, Input } from './ui'
import { workspaceApi } from '../lib/api'
import type { Document, IngestStatus } from '../lib/types'
import { fitPhonePage, type Size } from '../lib/page-transform'
import { VisualiseItButton } from '../viewer3d/VisualiseIt'
import './data-screen.css'
import { ShowOnTableButton } from './show-on-table'

const PAGE_SIZE = 40
const ACCEPTED = '.ifc,.dxf,.dwg,.pdf,.svg,.png,.jpg,.jpeg,.tif,.tiff'
const terminal = new Set(['ready', 'partial', 'failed', 'stored'])

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

function DocumentDetail({ doc, onClose, onAsk }: { doc: Document; onClose: () => void; onAsk: (doc: Document) => void }) {
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

  return <aside className="data-detail" aria-label="Document details" onKeyDown={(event) => { if (event.key === 'Escape') onClose() }}>
    <header><FileText size={24} /><div><h2><DocumentTitle title={doc.title} /></h2><small>/{doc.source}<span className="data-header-demo">{/generated for demo$/i.test(doc.title) ? ' · generated for demo' : ''}</span></small><details className="data-credit-info"><summary aria-label="Drawing credit and licence"><Info size={12} /></summary><div className="data-credit-popover"><dl><div><dt>Credit</dt><dd>{doc.credit || 'Not provided'}</dd></div><div><dt>Licence</dt><dd>{doc.licence || 'Not provided'}</dd></div></dl><div className="data-mobile-scene">{scene === 'available' ? <VisualiseItButton docId={doc.doc_id} /> : <button type="button" disabled={scene === 'loading'} onClick={() => setShowSceneNote(true)}>Visualise it</button>}{showSceneNote && <p role="status">{scene === 'error' ? 'Could not check 3D availability. Reopen the document to retry.' : 'No 3D scene available for this document.'}</p>}</div></div></details></div><ShowOnTableButton docId={doc.doc_id} sceneAvailable={scene === 'available'} /><button type="button" className="data-header-ask" aria-label="Ask about it" onClick={() => onAsk(doc)}><MessageSquare size={16} /></button><a className="data-compare" href="#/changes" aria-label="Compare document revisions"><GitCompare size={14} /><span>Compare</span></a><Button variant="ghost" size="icon" aria-label="Fit page" onClick={() => setZoom(100)}><Maximize2 size={16} /></Button><button ref={closeButton} type="button" className="data-close-detail" aria-label="Close document details" onClick={onClose}><X size={18} /></button></header>
    <div className="data-viewer-toolbar"><ChevronLeft size={14} /><span className="page-number">1</span><span>/ {doc.pages}</span><ChevronRight size={14} /><span className="toolbar-spacer" /><span className="data-viewer-tools" aria-hidden="true"><Search size={14} /><ScanText size={14} /><PenLine size={14} /></span><a aria-label="Download page" href={`/api/docs/${encodeURIComponent(doc.doc_id)}/pages/1/image`} download><Download size={14} /></a><span className="viewer-toolbar-divider" /><span className="data-zoom-controls"><Button variant="ghost" size="icon" aria-label="Zoom out" onClick={() => setZoom((n) => Math.max(25, n - 25))}><Minus size={14} /></Button><span aria-label="Page zoom level">{displayedZoom}%</span><Button variant="ghost" size="icon" aria-label="Zoom in" onClick={() => setZoom((n) => Math.min(400, n + 25))}><Plus size={14} /></Button></span></div>
    <div className="data-detail-body">
      <div ref={canvas} className="data-page-canvas"><div className={`data-page-plane ${phone ? 'phone-page-plane' : ''}`} style={phone && image && fitted ? {
        width: image.width, height: image.height, transform: `translate(${(viewport.width - image.width * phoneScale) / 2}px, ${fitted.y}px) scale(${phoneScale})`,
      } : { transform: `scale(${zoom / 100})` }}><DocumentImage key={doc.doc_id} doc={doc} preview onLoad={setImage} /></div></div>
      <dl className="data-document-credit"><div><dt>Credit</dt><dd>{doc.credit || 'Not provided'}</dd></div><div><dt>Licence</dt><dd>{doc.licence || 'Not provided'}</dd></div></dl>
      <div className="data-detail-actions"><Button variant="raised" onClick={() => onAsk(doc)}>Ask about it<ArrowRight size={15} /></Button>
        {scene === 'available' && <VisualiseItButton docId={doc.doc_id} />}</div>
      <p className="data-scene-note" role="status">{scene === 'loading' ? 'Checking for a 3D scene…' : scene === 'missing' ? 'No 3D scene available for this document.' : scene === 'error' ? 'Could not check 3D availability. Reopen the document to retry.' : '3D scene available.'}</p>
    </div>
  </aside>
}

export function DataScreen({ docs, loading, demo, hidden, onRefresh, onAsk }: {
  docs: Document[]; loading: boolean; demo: boolean; hidden: boolean
  onRefresh: () => Promise<void>; onAsk: (doc: Document) => void
}) {
  const [folder, setFolder] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [upload, setUpload] = useState<UploadState | null>(null)
  const [uploadError, setUploadError] = useState('')
  const [pollAttempt, setPollAttempt] = useState(0)
  const [dragging, setDragging] = useState(false)
  const uploadInput = useRef<HTMLInputElement>(null)
  const uploading = useRef(false)
  const lastOpened = useRef<HTMLButtonElement | null>(null)
  const pending = !!upload && !terminal.has(upload.status)

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
      setFolder('uploads')
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

  const sources = [...new Set(docs.map((doc) => doc.source))].sort()
  const activeFolder = folder === null ? sources[0] || '' : folder
  const query = search.trim().toLowerCase()
  // Searching always spans every source, even with a folder selected.
  const filtered = docs.filter((doc) => query ? `${doc.title} ${doc.doc_id} ${doc.source} ${doc.formats.join(' ')} ${doc.licence || ''} ${doc.credit || ''}`.toLowerCase().includes(query) : !activeFolder || doc.source === activeFolder)
  if (upload?.docId) filtered.sort((a, b) => Number(b.doc_id === upload.docId) - Number(a.doc_id === upload.docId))
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const currentPage = Math.min(page, pageCount)
  const visible = filtered.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE)
  const selected = docs.find((doc) => doc.doc_id === selectedId)
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
      {pending && !uploadError && <LoaderCircle size={16} className="data-spinner" />}<div><strong>{upload.name}</strong><p>{uploadLabel}</p>
        {!!upload.stages.length && <ul>{upload.stages.map((stage, index) => <li key={`${stage.stage}-${index}`}>{stage.stage}: {stage.ok ? 'complete' : 'unavailable'}</li>)}</ul>}
        {upload.detail && terminal.has(upload.status) && <p>{upload.detail}</p>}</div>
    </div>}
    {uploadError && <div className="data-upload-error"><p role="alert">{uploadError}</p>{upload?.docId && <Button variant="outline" onClick={async () => {
      setUploadError('')
      setPollAttempt((attempt) => attempt + 1)
      try { await onRefresh() } catch (error) { setUploadError(error instanceof Error ? error.message : 'Could not refresh documents.') }
    }}>Retry status</Button>}</div>}
    <div className={`data-browser ${selected ? 'has-detail' : ''}`}>
      <nav className="data-folders" aria-label="Document folders"><h2>Folders<FolderPlus size={14} /></h2>
        <button className="all-files" type="button" aria-current={!activeFolder && !query ? 'page' : undefined} onClick={() => { setFolder(''); setSearch(''); setPage(1) }}><Layers size={16} /><span>All Files</span><small>{docs.length}</small></button>
        {sources.map((source) => <div key={source}><button type="button" aria-label={`Open ${source} folder`} aria-current={activeFolder === source && !query ? 'page' : undefined} onClick={() => { setFolder(source); setSearch(''); setPage(1) }}>
          <Folder size={14} /><span>{source}</span><small>{docs.filter((doc) => doc.source === source).length}</small></button>
          {activeFolder === source && <div className="folder-file-tree">{docs.filter((doc) => doc.source === source).slice(0, 10).map((doc) => <button type="button" key={doc.doc_id} aria-label={`Preview ${doc.title}`} aria-current={selectedId === doc.doc_id ? 'page' : undefined} onClick={(event) => { lastOpened.current = event.currentTarget; setSelectedId(doc.doc_id) }}><FileText size={14} /><span className="document-title"><DocumentTitle title={doc.title} /></span></button>)}</div>}
        </div>)}
      </nav>
      <label className={`data-folder-search ${search ? 'has-query' : ''}`}><Search size={16} /><Input type="search" aria-label="Search documents" placeholder="Search all documents" value={search} onChange={(event) => { setSearch(event.target.value); setPage(1) }} /></label>
      <div className="data-files"><header><h2>{query ? 'Search results · all folders' : activeFolder || 'All Files'}</h2><ChevronLeft className="mobile-folder-back" size={14} /><select className="mobile-folder-select" aria-label="Document folder" value={activeFolder} onChange={(event) => { setFolder(event.target.value); setSearch(''); setPage(1) }}><option value="">All Files</option>{sources.map((source) => <option key={source} value={source}>{source}</option>)}</select><SlidersHorizontal className="mobile-folder-filter" size={14} /><span>Files ({filtered.length})</span></header>
        {loading ? <p className="data-empty" role="status">Loading documents…</p> : !visible.length ? <p className="data-empty">No documents found.</p> : <div className="data-file-list">{visible.map((doc) => <article key={doc.doc_id} className="data-file-row" data-doc-id={doc.doc_id} data-selected={selectedId === doc.doc_id || undefined}>
          <button className="data-open-file" type="button" aria-label={`Open ${doc.title}`} aria-expanded={selectedId === doc.doc_id} onClick={(event) => { lastOpened.current = event.currentTarget; setSelectedId(doc.doc_id) }}>
            <span className="file-checkbox" aria-hidden="true" /><DocumentImage key={doc.doc_id} doc={doc} /><span><h3><DocumentTitle title={doc.title} /></h3><span className="data-file-meta">{doc.source} · {doc.pages} {doc.pages === 1 ? 'page' : 'pages'}</span><small>{doc.licence || 'Licence not provided'} · {doc.credit || 'Credit not provided'}</small></span>
          </button><FormatBadges doc={doc} /><MoreHorizontal className="file-row-more" size={16} />
        </article>)}</div>}
        {!loading && filtered.length > 0 && <div className="data-pagination" aria-label="Document pagination"><span>{(currentPage - 1) * PAGE_SIZE + 1}–{Math.min(currentPage * PAGE_SIZE, filtered.length)} of {filtered.length}</span>
          <Button variant="ghost" size="icon" aria-label="Previous document page" disabled={currentPage === 1} onClick={() => setPage(currentPage - 1)}><ChevronLeft size={17} /></Button>
          <span>Page {currentPage} of {pageCount}</span><Button variant="ghost" size="icon" aria-label="Next document page" disabled={currentPage === pageCount} onClick={() => setPage(currentPage + 1)}><ChevronRight size={17} /></Button></div>}
      </div>
      {selected && <DocumentDetail key={selected.doc_id} doc={selected} onClose={closeDetail} onAsk={onAsk} />}
    </div>
  </section>
}
