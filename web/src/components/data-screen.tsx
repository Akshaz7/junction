import { searchDocuments } from '../lib/doc-search'
import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { ArrowRight, Box, ChevronDown, ChevronLeft, ChevronRight, Download, File, FileImage, FileText, Folder, GitCompare, Info, Layers, Maximize2, MessageSquare, Minus, Plus, Search, Upload, X } from 'lucide-react'
import { Badge, Button, Input } from './ui'
import { workspaceApi } from '../lib/api'
import type { Document } from '../lib/types'
import { fitPhonePage, type Size } from '../lib/page-transform'
import { DrawingModel, ViewerModeToggle, type ViewerMode } from './drawing-model'
import './data-screen.css'
import { ShowOnTableButton } from './show-on-table'
import { UploadDialog } from './upload-dialog'
import { ConnectionPill } from './connection-pill'
import { findSheetText, loadSheetText, type SheetText } from './viewer-tools/sheet-text'
import { useDialogFocus } from '../lib/use-dialog-focus'

const PAGE_SIZE = 40

type Version = { doc_id: string; index: number; date: string | null; size: number | null; label: string }
export type FileDocument = Document & {
  folder?: string; size?: number | null; updated_at?: string | null; date?: string | null
  version_count?: number | null; version_index?: number | null; versions?: Version[]
}
type FolderNode = { name: string; path: string; count: number; children: FolderNode[] }
const inFolder = (doc: FileDocument, path: string) => !path || doc.folder === path || !!doc.folder?.startsWith(`${path}/`)
function fileSize(size?: number | null) {
  if (size == null || !Number.isFinite(size) || size < 0) return null
  if (size < 1024) return `${size} B`
  return size < 1024 * 1024 ? `${(size / 1024).toFixed(1)} KB` : `${(size / (1024 * 1024)).toFixed(1)} MB`
}
function fileDate(value?: string | null) {
  return value && !Number.isNaN(Date.parse(value)) ? new Date(value).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) : null
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
function DocumentImage({ doc, preview = false, page = 1, onLoad }: { doc: Document; preview?: boolean; page?: number; onLoad?: (size: Size) => void }) {
  const [failed, setFailed] = useState(false)
  const Icon = doc.kind === 'ifc' || doc.kind === 'dxf' || doc.kind === 'dwg' ? Box : doc.kind === 'raster' || doc.kind === 'svg' ? FileImage : File
  return <span className={preview ? 'data-preview' : 'data-thumbnail'}>
    {!preview || failed ? <><Icon size={preview ? 56 : 18} aria-hidden="true" />{preview && <span>Page preview unavailable</span>}</> :
      <img loading="lazy" src={`/api/docs/${encodeURIComponent(doc.doc_id)}/${preview ? `pages/${page}/image` : 'files/page-1.thumb.png'}`}
        alt={preview ? `Page ${page} of ${doc.title}` : ''} onError={() => setFailed(true)}
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
  const [page, setPage] = useState(1)
  const [searchOpen, setSearchOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [sheetText, setSheetText] = useState<SheetText[]>([])
  const [textStatus, setTextStatus] = useState('')
  const matches = findSheetText(sheetText, query)
  useEffect(() => {
    if (!searchOpen) return
    const controller = new AbortController()
    setSheetText([]); setTextStatus('Loading page text…')
    loadSheetText(doc.doc_id, page, controller.signal).then((text) => {
      if (controller.signal.aborted) return
      setSheetText(text); setTextStatus(text.length ? '' : 'No searchable text is available on this page.')
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setTextStatus(error instanceof Error ? error.message : 'Page text could not be loaded.')
    })
    return () => controller.abort()
  }, [doc.doc_id, page, searchOpen])
  function changePage(next: number) { setPage(next); setImage(null); setZoom(100); setSheetText([]) }
  const [image, setImage] = useState<Size | null>(null)
  const [viewport, setViewport] = useState<Size>({ width: 0, height: 0 })
  const [phone, setPhone] = useState(() => window.matchMedia('(max-width: 640px)').matches)
  const canvas = useRef<HTMLDivElement>(null)
  const closeButton = useRef<HTMLButtonElement>(null)
  const panel = useRef<HTMLElement>(null)
  const credit = useRef<HTMLDetailsElement>(null)
  const searchTrigger = useRef<HTMLButtonElement>(null)
  const returnFocus = useRef(document.activeElement as HTMLElement | null)
  const titleId = useId()
  const sheet = phone && !docked
  useDialogFocus(sheet, panel, returnFocus, onClose)
  function closeSearch() { setSearchOpen(false); searchTrigger.current?.focus() }
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

  return <aside ref={panel} className="data-detail" data-docked={docked || undefined} role={sheet ? 'dialog' : undefined} aria-modal={sheet || undefined} aria-labelledby={sheet ? titleId : undefined} aria-label={sheet ? undefined : 'Document details'} tabIndex={sheet ? -1 : undefined} onKeyDown={(event) => {
    if (event.key !== 'Escape' || event.defaultPrevented) return
    event.preventDefault(); event.stopPropagation()
    if (credit.current?.open) { credit.current.open = false; credit.current.querySelector('summary')?.focus() }
    else if (searchOpen) closeSearch()
    else if (mode === '3d') changeMode('2d')
    else onClose()
  }}>
    <header><FileText size={24} /><div><h2 id={titleId}><DocumentTitle title={doc.title} /></h2><small>/{doc.source}<span className="data-header-demo">{/generated for demo$/i.test(doc.title) ? ' · generated for demo' : ''}</span></small><details ref={credit} className="data-credit-info"><summary aria-label="Drawing credit and licence"><Info size={12} /></summary><div className="data-credit-popover"><dl>{doc.credit && <div><dt>Credit</dt><dd>{doc.credit}</dd></div>}{doc.licence && <div><dt>Licence</dt><dd>{doc.licence}</dd></div>}</dl><div className="data-mobile-scene">{scene === 'available' && <button type="button" className="viewer3d-visualise-button" onClick={() => changeMode('3d')}>Visualise it</button>}</div></div></details></div>{scene === 'available' && <ViewerModeToggle mode={mode} onChange={changeMode} />}<ShowOnTableButton docId={doc.doc_id} sceneAvailable={scene === 'available'} /><button type="button" className="data-header-ask" aria-label="Ask about it" onClick={() => onAsk(doc)}><MessageSquare size={16} /></button><a className="data-compare" href="#/changes" aria-label="Compare document revisions"><GitCompare size={14} /><span>Compare</span></a><Button variant="ghost" size="icon" aria-label="Fit page" onClick={() => setZoom(100)}><Maximize2 size={16} /></Button><button ref={closeButton} type="button" className="data-close-detail" aria-label="Close document details" onClick={onClose}><X size={18} /></button></header>
    <div className="data-viewer-toolbar" hidden={mode === '3d'}><Button variant="ghost" size="icon-xs" aria-label="Previous drawing page" disabled={page <= 1} onClick={() => changePage(page - 1)}><ChevronLeft size={14} /></Button><span className="page-number">{page}</span><span>/ {doc.pages}</span><Button variant="ghost" size="icon-xs" aria-label="Next drawing page" disabled={page >= doc.pages} onClick={() => changePage(page + 1)}><ChevronRight size={14} /></Button><span className="toolbar-spacer" /><Button variant="ghost" size="icon-xs" aria-label="Search page text" aria-expanded={searchOpen} aria-controls="data-page-search" onClick={(event) => { searchTrigger.current = event.currentTarget; if (searchOpen) closeSearch(); else setSearchOpen(true) }}><Search size={14} /></Button><a aria-label="Download page" href={`/api/docs/${encodeURIComponent(doc.doc_id)}/pages/${page}/image`} download><Download size={14} /></a><span className="viewer-toolbar-divider" /><span className="data-zoom-controls"><Button variant="ghost" size="icon" aria-label="Zoom out" onClick={() => setZoom((n) => Math.max(25, n - 25))}><Minus size={14} /></Button><span aria-label="Page zoom level">{displayedZoom}%</span><Button variant="ghost" size="icon" aria-label="Zoom in" onClick={() => setZoom((n) => Math.min(400, n + 25))}><Plus size={14} /></Button></span></div>
    {searchOpen && mode === '2d' && <section className="data-page-search" id="data-page-search" aria-label="Page text search">
      <label>Find on page {page}<Input autoFocus type="search" aria-label="Find in page text" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
      <Button variant="ghost" size="icon-xs" aria-label="Close page search" onClick={closeSearch}><X size={14} /></Button>
      <p role="status">{textStatus || (query.trim() ? `${matches.length} matches on page ${page}` : 'Enter text to search this page.')}</p>
      {!!matches.length && <ul>{matches.map((match, index) => <li key={index}>{match.text}</li>)}</ul>}
    </section>}
    <div className="data-detail-body" hidden={mode === '3d'}>
      <div ref={canvas} className="data-page-canvas"><div className={`data-page-plane ${phone ? 'phone-page-plane' : ''}`} style={phone && image && fitted ? {
        width: image.width, height: image.height, transform: `translate(${(viewport.width - image.width * phoneScale) / 2}px, ${fitted.y}px) scale(${phoneScale})`,
      } : { transform: `scale(${zoom / 100})` }}><DocumentImage key={`${doc.doc_id}:${page}`} doc={doc} page={page} preview onLoad={setImage} /></div></div>
      <dl className="data-document-credit">{doc.credit && <div><dt>Credit</dt><dd>{doc.credit}</dd></div>}{doc.licence && <div><dt>Licence</dt><dd>{doc.licence}</dd></div>}</dl>
      <div className="data-detail-actions"><Button variant="raised" onClick={() => onAsk(doc)}>Ask about it<ArrowRight size={15} /></Button>
        {scene === 'available' && <button type="button" className="viewer3d-visualise-button" onClick={() => changeMode('3d')}>Visualise it</button>}</div>
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
  const [uploadOpen, setUploadOpen] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const lastOpened = useRef<HTMLButtonElement | null>(null)

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
  const filtered = query ? searchDocuments(docs, query) : docs.filter((doc) => inFolder(doc, activeFolder))
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
    <div className={`data-browser ${selected ? 'has-detail' : ''}`}>
      <nav className="data-folders" aria-label="Document folders"><h2>Folders</h2>
        <button className="all-files" type="button" aria-current={!activeFolder && !query ? 'page' : undefined} onClick={() => { setFolder(''); setSearch(''); setPage(1) }}><Layers size={16} /><span>All Files</span><small>{docs.length}</small></button>
        {folderLoading && <p role="status" className="data-folder-message">Loading folders…</p>}
        {folderError && <div className="data-folder-message"><p role="alert">{folderError}</p><button type="button" onClick={() => setFolderRetry((n) => n + 1)}>Retry folders</button></div>}
        {folders.map((node) => <FolderBranch key={node.path} node={node} active={query ? '' : activeFolder} onSelect={(path) => { setFolder(path); setSearch(''); setPage(1) }} />)}
      </nav>
      <label className={`data-folder-search ${search ? 'has-query' : ''}`}><Search size={16} /><Input type="search" aria-label="Search documents" placeholder="Search all documents" value={search} onChange={(event) => { setSearch(event.target.value); setPage(1) }} /></label>
      <div className="data-files"><header><h2>{query ? 'Search results · all folders' : activeFolder || 'All Files'}</h2><select className="mobile-folder-select" aria-label="Document folder" value={activeFolder} onChange={(event) => { setFolder(event.target.value); setSearch(''); setPage(1) }}><option value="">All Files</option>{options.map((option) => <option key={option.path} value={option.path}>{option.label}</option>)}</select><span>Files ({filtered.length})</span></header>
        {loading ? <p className="data-empty" role="status">Loading documents…</p> : !visible.length ? <div className="data-empty"><p>{query ? 'No documents match' : 'No documents yet.'}</p><div className="data-empty-actions">{(query || activeFolder) && <Button variant="outline" onClick={() => { setSearch(''); setFolder(''); setPage(1) }}>{query ? 'Clear search' : 'All files'}</Button>}<Button variant="raised" disabled={demo} onClick={openUpload}>Upload</Button></div></div> : <div className="data-file-list">{visible.map((doc) => <article key={doc.doc_id} className="data-file-row" data-doc-id={doc.doc_id} data-selected={selectedId === doc.doc_id || undefined}>
          <button className="data-open-file" type="button" aria-label={`Open ${doc.title}`} aria-expanded={selectedId === doc.doc_id} onClick={(event) => { lastOpened.current = event.currentTarget; setPreviewDocked(false); setSelectedId(doc.doc_id) }}>
            <DocumentImage key={doc.doc_id} doc={doc} /><span><h3><DocumentTitle title={doc.title} /></h3><span className="data-file-meta">{doc.folder || doc.source} · {doc.pages} {doc.pages === 1 ? 'page' : 'pages'}</span><small>{doc.licence || 'Licence not provided'} · {doc.credit || 'Credit not provided'}</small></span>
          </button><div className="data-file-facts">{fileSize(doc.size) !== null && <span aria-label="File size">{fileSize(doc.size)}</span>}{fileDate(doc.date || doc.updated_at) && <time aria-label="File date" dateTime={doc.date || doc.updated_at || undefined}>{fileDate(doc.date || doc.updated_at)}</time>}
            {doc.versions?.length ? <label className="data-version-picker"><span>{doc.version_count ?? doc.versions.length} versions</span><select aria-label={`Versions of ${doc.title}`} value={doc.versions.some((version) => version.doc_id === selectedId) ? selectedId! : doc.doc_id} disabled={versionLoading} onChange={(event) => void openVersion(event.target.value)}>{doc.versions.map((version) => <option key={version.doc_id} value={version.doc_id}>{version.label}</option>)}</select></label> : doc.version_count != null && Number.isFinite(doc.version_count) && <span>{doc.version_count} {doc.version_count === 1 ? 'version' : 'versions'}</span>}
          </div><FormatBadges doc={doc} />
        </article>)}</div>}
        {!loading && filtered.length > 0 && <div className="data-pagination" aria-label="Document pagination"><span>{(currentPage - 1) * PAGE_SIZE + 1}–{Math.min(currentPage * PAGE_SIZE, filtered.length)} of {filtered.length}</span>
          <Button variant="ghost" size="icon" aria-label="Previous document page" disabled={currentPage === 1} onClick={() => setPage(currentPage - 1)}><ChevronLeft size={17} /></Button>
          <span>Page {currentPage} of {pageCount}</span><Button variant="ghost" size="icon" aria-label="Next document page" disabled={currentPage === pageCount} onClick={() => setPage(currentPage + 1)}><ChevronRight size={17} /></Button></div>}
      </div>
      {selected && <DocumentDetail key={selected.doc_id} doc={selected} docked={previewDocked} onClose={closeDetail} onAsk={onAsk} />}
    </div>
  </section></>
}
