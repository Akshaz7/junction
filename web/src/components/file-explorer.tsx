import { ReadOnceChip } from './read-once-chip'
import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { ArrowRight, Box, ChevronLeft, ChevronRight, Download, File, FileImage, FileText, Folder, GitCompare, Info, Maximize2, MessageSquare, Minus, Plus, Search, X } from 'lucide-react'
import { Badge, Button, Input } from './ui'
import { workspaceApi } from '../lib/api'
import type { Document } from '../lib/types'
import { fitPhonePage, type Size } from '../lib/page-transform'
import { DrawingModel, ViewerModeToggle, type ViewerMode } from './drawing-model'
import './data-screen.css'
import { ShowOnTableButton } from './show-on-table'
import { findSheetText, loadSheetText, type SheetText } from './viewer-tools/sheet-text'
import { useDialogFocus } from '../lib/use-dialog-focus'


export function fileSize(size?: number | null) {
  if (size == null || !Number.isFinite(size) || size < 0) return null
  if (size < 1024) return `${size} B`
  return size < 1024 * 1024 ? `${(size / 1024).toFixed(1)} KB` : `${(size / (1024 * 1024)).toFixed(1)} MB`
}
export function fileDate(value?: string | null) {
  return value && !Number.isNaN(Date.parse(value)) ? new Date(value).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) : null
}

export function DocumentTitle({ title }: { title: string }) {
  const suffix = title.match(/^(.*?)(\s*[—–-]?\s*generated for demo)$/i)
  return suffix ? <><span className="document-title-name">{suffix[1]}</span><small className="document-demo-label">{suffix[2]}</small></> : <span className="document-title-name">{title}</span>
}
export function DocumentImage({ doc, preview = false, page = 1, onLoad }: { doc: Document; preview?: boolean; page?: number; onLoad?: (size: Size) => void }) {
  const [failed, setFailed] = useState(false)
  const Icon = doc.kind === 'ifc' || doc.kind === 'dxf' || doc.kind === 'dwg' ? Box : doc.kind === 'raster' || doc.kind === 'svg' ? FileImage : File
  return <span className={preview ? 'data-preview' : 'data-thumbnail'}>
    {!preview || failed ? <><Icon size={preview ? 56 : 18} aria-hidden="true" />{preview && <span>Page preview unavailable</span>}</> :
      <img loading="lazy" src={`/api/docs/${encodeURIComponent(doc.doc_id)}/${preview ? `pages/${page}/image` : 'files/page-1.thumb.png'}`}
        alt={preview ? `Page ${page} of ${doc.title}` : ''} onError={() => setFailed(true)}
        onLoad={(event) => onLoad?.({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })} />}
  </span>
}

export function FormatBadges({ doc }: { doc: Document }) {
  return <span className="data-formats">{doc.formats.map((format) => <Badge key={format}>{format.toUpperCase()}</Badge>)}</span>
}

export function DocumentDetail({ doc, docked, onClose, onAsk, actionsExtra }: { doc: Document; docked: boolean; onClose: () => void; onAsk: (doc: Document) => void; actionsExtra?: ReactNode }) {
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
    <header><FileText size={24} /><div><h2 id={titleId}><DocumentTitle title={doc.title} /></h2><small>/{doc.source}<span className="data-header-demo">{/generated for demo$/i.test(doc.title) ? ' · generated for demo' : ''}</span><ReadOnceChip docId={doc.doc_id} /></small><details ref={credit} className="data-credit-info"><summary aria-label="Drawing credit and licence"><Info size={12} /></summary><div className="data-credit-popover"><dl>{doc.credit && <div><dt>Credit</dt><dd>{doc.credit}</dd></div>}{doc.licence && <div><dt>Licence</dt><dd>{doc.licence}</dd></div>}</dl><div className="data-mobile-scene">{scene === 'available' && <button type="button" className="viewer3d-visualise-button" onClick={() => changeMode('3d')}>Visualise it</button>}</div></div></details></div>{scene === 'available' && <ViewerModeToggle mode={mode} onChange={changeMode} />}<ShowOnTableButton docId={doc.doc_id} sceneAvailable={scene === 'available'} /><button type="button" className="data-header-ask" aria-label="Ask about it" onClick={() => onAsk(doc)}><MessageSquare size={16} /></button><a className="data-compare" href="#/changes" aria-label="Compare document revisions"><GitCompare size={14} /><span>Compare</span></a><Button variant="ghost" size="icon" aria-label="Fit page" onClick={() => setZoom(100)}><Maximize2 size={16} /></Button><button ref={closeButton} type="button" className="data-close-detail" aria-label="Close document details" onClick={onClose}><X size={18} /></button></header>
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
      <div className="data-detail-actions"><Button variant="raised" onClick={() => onAsk(doc)}>Ask about it<ArrowRight size={15} /></Button>{actionsExtra}
        {scene === 'available' && <button type="button" className="viewer3d-visualise-button" onClick={() => changeMode('3d')}>Visualise it</button>}</div>
      <p className="data-scene-note" role="status">{scene === 'loading' ? 'Checking for a 3D scene…' : scene === 'missing' ? 'No 3D scene available for this document.' : scene === 'error' ? 'Could not check 3D availability. Reopen the document to retry.' : '3D scene available.'}</p>
    </div>
    {modelVisited && <div className="viewer-model-slot" hidden={mode !== '3d'}><DrawingModel docId={doc.doc_id} /></div>}
  </aside>
}


/** One entry of the Folders card (also "All Files"). Same look as the Data screen's folder buttons. */
export function FolderItem({ label, count, current, onClick, icon }: { label: string; count: number; current: boolean; onClick: () => void; icon?: ReactNode }) {
  return <button type="button" aria-current={current ? 'page' : undefined} aria-label={`Open ${label} folder`} onClick={onClick}>{icon ?? <Folder size={14} />}<span>{label}</span><small>{count}</small></button>
}

/** The Data screen's layout: Folders card on the left, Files card in the middle, detail viewer on the right. */
export function ExplorerBrowser({ detail, nav, search, title, count, mobileFolder, actions, children }: {
  detail: ReactNode; nav: ReactNode; search?: ReactNode; title: string; count: number; mobileFolder?: ReactNode; actions?: ReactNode; children: ReactNode
}) {
  return <div className={`data-browser ${detail ? 'has-detail' : ''}`}>
    <nav className="data-folders" aria-label="Document folders"><h2>Folders</h2>{nav}</nav>
    {search}
    <div className="data-files"><header><h2>{title}</h2>{mobileFolder}<span>Files ({count})</span>{actions}</header>{children}</div>
    {detail}
  </div>
}

/** A file row: type tile, name (truncated, full name in the tooltip), meta line, facts, format badges, optional menu. */
export function FileRow({ doc, meta, sub, facts, selected, expanded, onOpen, trailing, status }: {
  doc: Document; meta: ReactNode; sub?: ReactNode; facts?: ReactNode; selected: boolean; expanded?: boolean
  onOpen: (button: HTMLButtonElement) => void; trailing?: ReactNode; status?: 'busy' | 'bad'
}) {
  return <article className="data-file-row" data-doc-id={doc.doc_id} data-selected={selected || undefined} data-status={status}>
    <button className="data-open-file" type="button" aria-label={`Open ${doc.title}`} aria-expanded={expanded ?? selected} title={doc.title} onClick={(event) => onOpen(event.currentTarget)}>
      <DocumentImage key={doc.doc_id} doc={doc} /><span><h3 title={doc.title}><DocumentTitle title={doc.title} /></h3><span className="data-file-meta">{meta}</span>{sub && <small>{sub}</small>}</span>
    </button>
    {facts && <div className="data-file-facts">{facts}</div>}
    <FormatBadges doc={doc} />{trailing}
  </article>
}
