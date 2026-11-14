import { describe, expect, it } from 'vitest'
import type { Document } from './types'
import { MAX_UPLOAD_BYTES, uploadProgress, uploadReducer, validateUpload, type UploadState } from './upload-state'

const file = new File(['drawing'], 'Floor Plan.PDF', { type: 'application/pdf' })
const document = { doc_id: 'uploads__floor', title: 'Floor plan' } as Document

describe('upload state machine', () => {
  it('shows ready with a processing flag when readable, then settles when ingestion ends', () => {
    const file = new File(['x'], 'plan.png')
    const document = { doc_id: 'd1' } as never
    let state = uploadReducer({ status: 'idle' }, { type: 'start', file })
    state = uploadReducer(state, { type: 'uploaded', docId: 'd1' })
    state = uploadReducer(state, { type: 'ready', document, processing: true })
    expect(state).toMatchObject({ status: 'ready', processing: true })
    state = uploadReducer(state, { type: 'ready', document })
    expect(state).toMatchObject({ status: 'ready' })
    expect((state as { processing?: boolean }).processing).toBeUndefined()
  })

  it('moves idle → uploading → processing → ready with separate progress', () => {
    let state: UploadState = { status: 'idle' }
    state = uploadReducer(state, { type: 'start', file })
    expect(state).toMatchObject({ status: 'uploading', progress: 0, file })
    state = uploadReducer(state, { type: 'upload-progress', progress: 0.8 })
    expect(state).toMatchObject({ status: 'uploading', progress: 0.8 })
    state = uploadReducer(state, { type: 'uploaded', docId: document.doc_id })
    expect(state).toMatchObject({ status: 'processing', progress: null })
    state = uploadReducer(state, { type: 'processing-progress', step: 'Reading pages', progress: 0.25 })
    expect(state).toMatchObject({ status: 'processing', step: 'Reading pages', progress: 0.25 })
    state = uploadReducer(state, { type: 'ready', document })
    expect(state).toMatchObject({ status: 'ready', document, file })
    expect(uploadReducer(state, { type: 'upload-progress', progress: 0.9 })).toBe(state)
  })

  it('fails uploading with a reason and supports starting again', () => {
    const started = uploadReducer({ status: 'idle' }, { type: 'start', file })
    const failed = uploadReducer(started, { type: 'failed', reason: 'Connection lost', retry: 'upload' })
    expect(failed).toMatchObject({ status: 'failed', file, reason: 'Connection lost', retry: 'upload' })
    expect(uploadReducer(failed, { type: 'start', file }).status).toBe('uploading')
  })

  it('keeps the document ID on polling failure so retry resumes without uploading again', () => {
    const failed = uploadReducer({ status: 'processing', file, docId: document.doc_id, step: '', progress: 0.5 }, {
      type: 'failed', reason: 'Cannot check progress', retry: 'poll',
    })
    expect(uploadReducer(failed, { type: 'resume' })).toMatchObject({ status: 'processing', file, docId: document.doc_id })
    const ingestFailed = uploadReducer(failed, { type: 'failed', reason: 'Invalid PDF', retry: 'upload' })
    expect(uploadReducer(ingestFailed, { type: 'resume' })).toBe(ingestFailed)
  })

  it('ignores premature and wrong-document completions and resets for a new session', () => {
    const idle: UploadState = { status: 'idle' }
    expect(uploadReducer(idle, { type: 'ready', document })).toBe(idle)
    const processing: UploadState = { status: 'processing', file, docId: 'other', step: '', progress: null }
    expect(uploadReducer(processing, { type: 'ready', document })).toBe(processing)
    expect(uploadReducer(processing, { type: 'reset' })).toEqual(idle)
  })

  it('clears the previous file when a new selection fails validation', () => {
    expect(uploadReducer({ status: 'ready', file, docId: document.doc_id, document }, {
      type: 'failed', reason: 'Choose one drawing at a time.', retry: 'choose',
    })).toEqual({ status: 'failed', reason: 'Choose one drawing at a time.', retry: 'choose', file: undefined, docId: undefined })
  })

  it.each(['plan.pdf', 'plan.PNG', 'plan.jpg', 'plan.JPEG', 'plan.dxf', 'plan.ifc'])('accepts %s including browsers with no CAD MIME type', (name) => {
    expect(validateUpload({ name, size: 1 })).toBeNull()
  })

  it('rejects unsupported, empty and oversized files before upload', () => {
    expect(validateUpload({ name: 'plan.pdf.exe', size: 1 })).toContain('Choose a PDF')
    expect(validateUpload({ name: 'plan', size: 1 })).toContain('Choose a PDF')
    expect(validateUpload({ name: 'plan.pdf', size: 0 })).toContain('empty')
    expect(validateUpload({ name: 'plan.ifc', size: MAX_UPLOAD_BYTES + 1 })).toContain('100 MiB')
    expect(validateUpload({ name: 'plan.ifc', size: MAX_UPLOAD_BYTES })).toBeNull()
    expect(uploadReducer({ status: 'idle' }, { type: 'start', file: new File([], 'plan.pdf') })).toMatchObject({ status: 'failed', retry: 'choose' })
  })

  it('uses indeterminate progress for missing measurements and bounds measured values', () => {
    expect(uploadProgress(undefined)).toBeNull()
    expect(uploadProgress(NaN)).toBeNull()
    expect(uploadProgress(Infinity)).toBeNull()
    expect(uploadProgress(-1)).toBe(0)
    expect(uploadProgress(4)).toBe(1)
  })
})
