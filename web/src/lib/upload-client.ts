import type { Document, UploadReceipt } from './types'
import { uploadProgress, validateUpload } from './upload-state'

export class UploadError extends Error {
  /** `ambiguous`: the request failed after bytes may have been stored (5xx, dropped connection, timeout). */
  constructor(message: string, readonly retry: 'upload' | 'poll' = 'upload', readonly ambiguous = false) { super(message) }
}

function responseReason(body: unknown, fallback: string): string {
  if (body && typeof body === 'object') {
    const data = body as Record<string, unknown>
    for (const key of ['reason', 'detail', 'message']) {
      if (typeof data[key] === 'string' && data[key].trim()) return data[key]
    }
  }
  return fallback
}

/** XHR supplies actual bytes sent; fetch has no browser upload-progress callback. */
export function uploadFile(file: File, signal: AbortSignal, onProgress: (fraction: number | null) => void,
  createRequest: () => XMLHttpRequest = () => new XMLHttpRequest()): Promise<UploadReceipt> {
  return new Promise((resolve, reject) => {
    const invalid = validateUpload(file)
    if (invalid) { reject(new UploadError(invalid)); return }
    if (signal.aborted) { reject(new DOMException('Upload cancelled.', 'AbortError')); return }
    const xhr = createRequest()
    const abort = () => xhr.abort()
    const finish = (error?: Error, receipt?: UploadReceipt) => {
      signal.removeEventListener('abort', abort)
      if (error) reject(error)
      else resolve(receipt!)
    }
    xhr.open('POST', '/api/upload')
    xhr.timeout = 120_000
    xhr.upload.onprogress = (event) => onProgress(event.lengthComputable && event.total > 0 ? uploadProgress(event.loaded / event.total) : null)
    xhr.onload = () => {
      let body: unknown
      try { body = JSON.parse(xhr.responseText) } catch { /* Proxies can return HTML. */ }
      if (xhr.status < 200 || xhr.status >= 300) {
        finish(new UploadError(responseReason(body, xhr.status === 413 ? 'This file is too large for the server. Try a smaller file.' : `Upload failed (${xhr.status}). Please try again.`), 'upload', xhr.status >= 500))
      } else if (!body || typeof body !== 'object' || !('doc_id' in body) || typeof body.doc_id !== 'string' || !body.doc_id) {
        finish(new UploadError('The server did not return a document ID. Please try again.'))
      } else finish(undefined, body as UploadReceipt)
    }
    xhr.onerror = () => finish(new UploadError('The upload could not reach the server. Check your connection and try again.', 'upload', true))
    xhr.ontimeout = () => finish(new UploadError('The upload timed out. Try again or choose a smaller file.', 'upload', true))
    xhr.onabort = () => finish(new DOMException('Upload cancelled.', 'AbortError'))
    signal.addEventListener('abort', abort, { once: true })
    const body = new FormData()
    body.append('file', file)
    xhr.send(body)
  })
}

/**
 * After an ambiguous failure, ask the server whether the file was in fact stored. If so the upload succeeded and only
 * processing remains; telling the user to retry would create a duplicate.
 */
export async function findPersistedUpload(file: File, startedAt: number, transport: typeof fetch = fetch): Promise<UploadReceipt | null> {
  try {
    const response = await transport('/api/docs')
    if (!response.ok) return null
    const body = await response.json() as { sources?: { docs?: { doc_id: string; title?: string; size?: number; updated_at?: string }[] }[] }
    const stem = file.name.replace(/\.[^.]+$/, '')
    const hit = (body.sources ?? []).flatMap((source) => source.docs ?? []).filter((doc) => doc.doc_id.startsWith('uploads__') && doc.title === stem
      && (doc.size == null || doc.size === file.size) && (!doc.updated_at || Date.parse(doc.updated_at) >= startedAt - 5000))
      .sort((a, b) => Date.parse(b.updated_at ?? '') - Date.parse(a.updated_at ?? ''))[0]
    return hit ? { doc_id: hit.doc_id, status: 'ingesting' } as UploadReceipt : null
  } catch { return null }
}

const stageNames: Record<string, string> = {
  scene: 'Building 3D', ifc_scene: 'Building 3D', ifc_index: 'Reading model quantities', extrude: 'Building 3D', usdz: 'Preparing AR model',
  publish: 'Finishing up', pool: 'Finishing up',
}
/** The server's internal stage name as plain words. */
export function friendlyStage(step: string | undefined) {
  if (!step) return ''
  const key = step.trim().toLowerCase().replace(/ /g, '_')
  return stageNames[key] ?? 'Reading drawing'
}

/** A user-facing failure message; the raw server text, when different, is kept for a details expander. */
export function friendlyFailure(reason: string): { message: string; raw: string } {
  const raw = reason.trim()
  if (/no (3d )?geometry|has no geometry|usdz|ifcconvert|zero (meshes|geometry)/i.test(raw)) return { message: 'This file has no 3D geometry we can convert.', raw }
  if (/runtimeerror|traceback|exception|error:|\bat line\b|\.py\b/i.test(raw)) return { message: 'We could not process this file. Try again, or try a different drawing.', raw }
  return { message: raw, raw: '' }
}

type Ingest = { status?: string; readable?: boolean; step?: string; progress?: number; detail?: string; reason?: string }
type UploadDocument = Document & { status?: string; ingest?: Ingest; ingest_status?: string }
type PollOptions = {
  signal: AbortSignal
  onProgress: (step: string, progress: number | null) => void
  /** Fires once when pages and text exist (ingest `readable`) while processing continues. */
  onReadable?: (document: Document, note?: string) => void
  transport?: typeof fetch
  intervalMs?: number
  timeoutMs?: number
}

function pause(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const abort = () => { clearTimeout(timer); reject(new DOMException('Cancelled.', 'AbortError')) }
    const timer = setTimeout(() => { signal.removeEventListener('abort', abort); resolve() }, ms)
    signal.addEventListener('abort', abort, { once: true })
    if (signal.aborted) { signal.removeEventListener('abort', abort); abort() }
  })
}

/** A legacy document row exists before ingestion finishes; existence alone is not readiness. */
export async function waitForUpload(docId: string, options: PollOptions): Promise<{ document: Document; note?: string }> {
  const { signal, onProgress, onReadable, transport = fetch, intervalMs = 1500, timeoutMs = 300_000 } = options
  const path = `/api/docs/${encodeURIComponent(docId)}`
  const deadline = Date.now() + timeoutMs
  const bounded = AbortSignal.any([signal, AbortSignal.timeout(timeoutMs)])
  let legacy = false
  let announcedReadable = false
  async function readDocument(): Promise<UploadDocument> {
    const response = await transport(path, { signal: bounded })
    if (!response.ok) throw new UploadError(responseReason(await response.json().catch(() => null), `Could not read the document (${response.status}). Try again to check its progress.`), 'poll')
    const document = await response.json() as UploadDocument
    if (document.doc_id !== docId) throw new UploadError('The server returned a different document. Try checking again.', 'poll')
    return document
  }
  try {
    while (Date.now() < deadline) {
      bounded.throwIfAborted()
      let status: Ingest
      let document: UploadDocument | undefined
      if (!legacy) {
        const response = await transport(`${path}/ingest`, { signal: bounded })
        if ([404, 405, 501].includes(response.status)) legacy = true
        else if (!response.ok) throw new UploadError(responseReason(await response.json().catch(() => null), `Could not check processing progress (${response.status}). Try again to check your upload.`), 'poll')
        if (!legacy) status = await response.json() as Ingest
        else status = {}
      } else status = {}
      if (legacy) {
        document = await readDocument()
        status = document.ingest ?? { status: document.ingest_status ?? document.status }
        // Older servers expose no ingest state on doc detail. Confirm a usable artifact.
        if (!status.status) {
          const artifact = document.kind === 'ifc' ? 'files/scene.json' : 'planmap/1'
          const response = await transport(`${path}/${artifact}`, { signal: bounded })
          if (response.ok) status = { status: 'ready', detail: 'Your drawing is available. Detailed processing progress is unavailable on this server.' }
          else if (response.status !== 404) throw new UploadError(`Could not check the drawing (${response.status}). Try checking again.`, 'poll')
        }
      }
      if (status.status === 'failed') throw new UploadError(status.reason || status.detail || 'This drawing could not be processed. Please try again.')
      if (status.status === 'ready' || status.status === 'partial') {
        return { document: document ?? await readDocument(), note: status.detail || (status.status === 'partial' ? 'Some drawing content could not be processed. Answers may be limited.' : undefined) }
      }
      if (status.status === 'none' || status.status === 'stored') throw new UploadError(status.reason || status.detail || 'Your file was saved, but processing is unavailable on this server. Please try again later.', 'poll')
      if (status.readable && !announcedReadable && onReadable) {
        announcedReadable = true
        const readable = document ?? await readDocument()
        if (status.detail) onReadable(readable, status.detail)
        else onReadable(readable)
      }
      onProgress(friendlyStage(status.step) || (legacy ? 'Checking your drawing. Detailed progress is unavailable…' : 'Preparing your drawing…'), uploadProgress(status.progress))
      await pause(intervalMs, bounded)
    }
    throw new UploadError('Processing is taking longer than expected. Try again to check this upload.', 'poll')
  } catch (error) {
    if (signal.aborted || error instanceof UploadError) throw error
    if (bounded.aborted) throw new UploadError('Processing is taking longer than expected. Try again to check this upload.', 'poll')
    throw new UploadError('Could not check processing progress. Check your connection and try again.', 'poll')
  }
}
