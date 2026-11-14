import type { Document } from './types'

// Matches server/files_routes.py. JPEG is also accepted as .jpeg.
export const MAX_UPLOAD_BYTES = 100 * 1024 * 1024
export const UPLOAD_ACCEPT = '.pdf,.png,.jpg,.jpeg,.dxf,.ifc'

export function validateUpload(file: Pick<File, 'name' | 'size'>): string | null {
  if (!/\.(pdf|png|jpe?g|dxf|ifc)$/i.test(file.name)) return 'Choose a PDF, PNG, JPG, DXF or IFC file.'
  if (file.size === 0) return 'This file is empty. Choose a file with drawing content.'
  if (file.size > MAX_UPLOAD_BYTES) return 'This file is too large. The maximum size is 100 MiB.'
  return null
}

export type UploadState =
  | { status: 'idle' }
  | { status: 'uploading'; file: File; progress: number | null }
  | { status: 'processing'; file: File; docId: string; step: string; progress: number | null }
  | { status: 'ready'; file: File; docId: string; document: Document; note?: string; processing?: boolean }
  | { status: 'failed'; file?: File; docId?: string; reason: string; retry: 'choose' | 'upload' | 'poll' }

export type UploadEvent =
  | { type: 'reset' }
  | { type: 'start'; file: File }
  | { type: 'uploaded'; docId: string }
  | { type: 'upload-progress'; progress: number | null }
  | { type: 'processing-progress'; step: string; progress: number | null }
  | { type: 'ready'; document: Document; note?: string; processing?: boolean }
  | { type: 'failed'; reason: string; retry: 'choose' | 'upload' | 'poll'; file?: File }
  | { type: 'resume' }

export function uploadProgress(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : null
}

export function uploadReducer(state: UploadState, event: UploadEvent): UploadState {
  switch (event.type) {
    case 'reset': return { status: 'idle' }
    case 'start': {
      const reason = validateUpload(event.file)
      return reason ? { status: 'failed', reason, retry: 'choose' } : { status: 'uploading', file: event.file, progress: 0 }
    }
    case 'upload-progress': return state.status === 'uploading' ? { ...state, progress: uploadProgress(event.progress) } : state
    case 'uploaded': return state.status === 'uploading' ? { status: 'processing', file: state.file, docId: event.docId, step: 'Preparing your drawing…', progress: null } : state
    case 'processing-progress': return state.status === 'processing' ? { ...state, step: event.step, progress: uploadProgress(event.progress) } : state
    case 'ready': return (state.status === 'processing' || state.status === 'ready') && event.document.doc_id === state.docId
      ? { status: 'ready', file: state.file, docId: state.docId, document: event.document, note: event.note, processing: event.processing } : state
    case 'failed': return {
      status: 'failed', file: event.retry === 'choose' ? undefined : event.file ?? ('file' in state ? state.file : undefined),
      docId: event.retry !== 'choose' && 'docId' in state ? state.docId : undefined, reason: event.reason, retry: event.retry,
    }
    case 'resume': return state.status === 'failed' && state.retry === 'poll' && state.file && state.docId
      ? { status: 'processing', file: state.file, docId: state.docId, step: 'Checking your drawing…', progress: null } : state
  }
}
