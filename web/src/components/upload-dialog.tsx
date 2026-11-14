import { useEffect, useId, useReducer, useRef, useState, type DragEvent } from 'react'
import { createPortal } from 'react-dom'
import { AlertCircle, ArrowRight, Check, FileText, Upload, X } from 'lucide-react'
import type { Document } from '../lib/types'
import { uploadFile, UploadError, waitForUpload } from '../lib/upload-client'
import { MAX_UPLOAD_BYTES, UPLOAD_ACCEPT, uploadReducer, validateUpload } from '../lib/upload-state'
import { Button } from './ui'
import './upload-dialog.css'

export type UploadDialogProps = {
  open: boolean
  onClose: () => void
  /** Mounting screen selects this document and opens its chat. */
  onAsk: (document: Document) => void
  /** Mounting screen selects this document and opens its viewer. */
  onOpen: (document: Document) => void
  onReady?: (document: Document) => void
}

/** Mount beside the upload trigger; navigation stays with the owning screen. */
export function UploadDialog(props: UploadDialogProps) {
  return props.open ? createPortal(<UploadSession {...props} />, document.body) : null
}

function UploadSession({ onClose, onAsk, onOpen, onReady }: UploadDialogProps) {
  const [state, dispatch] = useReducer(uploadReducer, { status: 'idle' })
  const [dragging, setDragging] = useState(false)
  const dialog = useRef<HTMLDialogElement>(null)
  const input = useRef<HTMLInputElement>(null)
  const request = useRef<AbortController | null>(null)
  const announced = useRef<string | null>(null)
  const titleId = useId()
  const descriptionId = useId()
  const busy = state.status === 'uploading' || state.status === 'processing'

  useEffect(() => {
    const element = dialog.current!
    const previous = document.activeElement
    element.showModal()
    return () => {
      request.current?.abort()
      element.close()
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus()
    }
  }, [])

  useEffect(() => {
    if (state.status === 'ready' && announced.current !== state.docId) {
      announced.current = state.docId
      onReady?.(state.document)
    }
  }, [state, onReady])

  function close() { request.current?.abort(); onClose() }

  async function monitor(docId: string, controller: AbortController) {
    const result = await waitForUpload(docId, {
      signal: controller.signal,
      onProgress: (step, progress) => { if (!controller.signal.aborted) dispatch({ type: 'processing-progress', step, progress }) },
    })
    if (!controller.signal.aborted) dispatch({ type: 'ready', ...result })
  }

  async function start(file: File) {
    if (request.current && !request.current.signal.aborted) return
    const invalid = validateUpload(file)
    if (invalid) { dispatch({ type: 'failed', reason: invalid, retry: 'choose' }); return }
    const controller = new AbortController()
    request.current = controller
    dispatch({ type: 'start', file })
    let phase: 'upload' | 'poll' = 'upload'
    try {
      const receipt = await uploadFile(file, controller.signal, (progress) => {
        if (!controller.signal.aborted) dispatch({ type: 'upload-progress', progress })
      })
      if (controller.signal.aborted) return
      dispatch({ type: 'uploaded', docId: receipt.doc_id })
      phase = 'poll'
      await monitor(receipt.doc_id, controller)
    } catch (error) {
      if (!controller.signal.aborted) dispatch({ type: 'failed', reason: error instanceof Error ? error.message : 'Could not upload this drawing. Please try again.', retry: error instanceof UploadError ? error.retry : phase })
    } finally {
      if (request.current === controller) request.current = null
    }
  }

  async function retry() {
    if (state.status !== 'failed') return
    if (state.retry === 'choose' || !state.file) { input.current?.click(); return }
    if (state.retry !== 'poll' || !state.docId) { void start(state.file); return }
    if (request.current) return
    const controller = new AbortController()
    request.current = controller
    dispatch({ type: 'resume' })
    try { await monitor(state.docId, controller) }
    catch (error) {
      if (!controller.signal.aborted) dispatch({ type: 'failed', reason: error instanceof Error ? error.message : 'Could not check processing progress.', retry: error instanceof UploadError ? error.retry : 'poll' })
    } finally { if (request.current === controller) request.current = null }
  }

  function choose(files: FileList | null) {
    if (!files?.length || busy) return
    if (files.length !== 1) { dispatch({ type: 'failed', reason: 'Choose one drawing at a time.', retry: 'choose' }); return }
    void start(files[0])
  }

  function drop(event: DragEvent) {
    event.preventDefault()
    setDragging(false)
    choose(event.dataTransfer.files)
  }

  const file = 'file' in state ? state.file : undefined
  const progress = busy ? state.progress : null
  return <dialog ref={dialog} className="upload-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={descriptionId}
    onCancel={(event) => { event.preventDefault(); close() }}>
    <header className="upload-dialog-header"><div className="upload-dialog-symbol"><Upload size={20} aria-hidden="true" /></div>
      <div><h2 id={titleId}>Upload a drawing</h2><p id={descriptionId}>Bring your plans into Hologram.</p></div>
      <Button variant="ghost" size="icon" aria-label="Close upload dialog" onClick={close}><X size={18} /></Button>
    </header>
    <input ref={input} className="upload-dialog-input" type="file" accept={UPLOAD_ACCEPT} aria-label="Choose a drawing"
      onChange={(event) => { choose(event.currentTarget.files); event.currentTarget.value = '' }} />

    {(state.status === 'idle' || state.status === 'failed') && <div className="upload-dialog-drop" data-dragging={dragging || undefined}
      onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = 'copy'; setDragging(true) }}
      onDragLeave={(event) => { if (!(event.relatedTarget instanceof Node) || !event.currentTarget.contains(event.relatedTarget)) setDragging(false) }} onDrop={drop}>
      <Upload size={28} aria-hidden="true" /><strong>Drag and drop your drawing here</strong><span>or choose a file from your device</span>
      <Button variant="outline" onClick={() => input.current?.click()}>Choose file</Button>
      <small>PDF, PNG, JPG, DXF or IFC · Up to {MAX_UPLOAD_BYTES / (1024 * 1024)} MiB</small>
    </div>}

    {file && <div className="upload-dialog-file"><FileText size={20} aria-hidden="true" /><div><strong>{file.name}</strong><small>{new Intl.NumberFormat('en', { maximumFractionDigits: 1 }).format(file.size / (1024 * 1024))} MiB</small></div>
      {state.status === 'ready' && <Check className="upload-dialog-check" size={20} aria-hidden="true" />}</div>}

    {busy && <section className="upload-dialog-progress" aria-label={state.status === 'uploading' ? 'Upload progress' : 'Drawing processing progress'}>
      <div role="status" aria-live="polite"><strong>{state.status === 'uploading' ? 'Uploading your drawing…' : 'Processing your drawing…'}</strong>
        <p>{state.status === 'uploading' ? 'Sending your file.' : state.step}</p></div>
      <div className="upload-dialog-progress-line"><progress max={1} value={progress ?? undefined} aria-label={state.status === 'uploading' ? 'File uploaded' : 'Drawing processed'} />
        <span>{progress === null ? 'In progress' : `${Math.round(progress * 100)}%`}</span></div>
      <small>{state.status === 'uploading' ? 'Keep this dialog open until the upload finishes.' : 'You can close this dialog while your drawing is processed. Find it in Data.'}</small>
    </section>}

    {state.status === 'failed' && <div className="upload-dialog-error" role="alert"><AlertCircle size={20} aria-hidden="true" /><div><strong>{state.retry === 'poll' ? 'Could not confirm processing' : state.docId ? 'Drawing could not be processed' : 'Drawing could not be uploaded'}</strong><p>{state.reason}</p>
      <Button variant="outline" onClick={() => { void retry() }}>Try again</Button></div></div>}

    {state.status === 'ready' && <section className="upload-dialog-ready"><p role="status"><Check size={18} aria-hidden="true" /><strong>Ready</strong></p>
      {state.note && <p className="upload-dialog-note">{state.note}</p>}
      <div className="upload-dialog-actions"><Button onClick={() => { onAsk(state.document); close() }}>Ready — Ask about it<ArrowRight size={16} /></Button>
        <Button variant="outline" onClick={() => { onOpen(state.document); close() }}>Open</Button></div>
    </section>}
    <footer className="upload-dialog-footer">AI can make mistakes. Verify important information.</footer>
  </dialog>
}
