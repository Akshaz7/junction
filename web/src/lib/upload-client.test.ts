import { afterEach, describe, expect, it, vi } from 'vitest'
import { findPersistedUpload, uploadFile, waitForUpload } from './upload-client'

const file = new File(['drawing'], 'plan.png', { type: 'image/png' })
const doc = { doc_id: 'uploads__plan', kind: 'raster', title: 'Plan', pages: 1 }
const controller = () => new AbortController()

function requestDouble() {
  const xhr = {
    open: vi.fn(), send: vi.fn(), abort: vi.fn(), timeout: 0,
    status: 200, responseText: JSON.stringify({ doc_id: doc.doc_id, status: 'ingesting' }),
    upload: { onprogress: null as ((event: Partial<ProgressEvent>) => void) | null },
    onload: null as (() => void) | null, onerror: null as (() => void) | null,
    ontimeout: null as (() => void) | null, onabort: null as (() => void) | null,
  }
  xhr.abort.mockImplementation(() => xhr.onabort?.())
  return { xhr, create: () => xhr as unknown as XMLHttpRequest }
}

afterEach(() => vi.useRealTimers())

describe('upload transport', () => {
  it('posts multipart and reports measured bytes, then waits for the server receipt', async () => {
    const { xhr, create } = requestDouble()
    const progress = vi.fn()
    const result = uploadFile(file, controller().signal, progress, create)
    expect(xhr.open).toHaveBeenCalledWith('POST', '/api/upload')
    expect((xhr.send.mock.calls[0][0] as FormData).get('file')).toEqual(file)
    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 5, total: 10 })
    xhr.upload.onprogress?.({ lengthComputable: false })
    expect(progress.mock.calls).toEqual([[0.5], [null]])
    xhr.onload?.()
    await expect(result).resolves.toMatchObject({ doc_id: doc.doc_id })
  })

  it('uses the readable API reason and handles HTML proxy failures', async () => {
    const { xhr, create } = requestDouble()
    xhr.status = 415
    xhr.responseText = JSON.stringify({ detail: 'Unsupported drawing format' })
    const result = uploadFile(file, controller().signal, vi.fn(), create)
    xhr.onload?.()
    await expect(result).rejects.toThrow('Unsupported drawing format')
    xhr.status = 413
    xhr.responseText = '<html>too large</html>'
    const large = uploadFile(file, controller().signal, vi.fn(), create)
    xhr.onload?.()
    await expect(large).rejects.toThrow('too large')
  })

  it.each(['onerror', 'ontimeout'] as const)('fails clearly on %s', async (event) => {
    const { xhr, create } = requestDouble()
    const result = uploadFile(file, controller().signal, vi.fn(), create)
    xhr[event]?.()
    await expect(result).rejects.toThrow(event === 'onerror' ? 'connection' : 'timed out')
  })

  it('aborts an active upload and removes the listener after completion', async () => {
    const { xhr, create } = requestDouble()
    const cancel = controller()
    const result = uploadFile(file, cancel.signal, vi.fn(), create)
    cancel.abort()
    expect(xhr.abort).toHaveBeenCalledOnce()
    await expect(result).rejects.toMatchObject({ name: 'AbortError' })
    xhr.abort.mockClear()
    const next = controller()
    const completed = uploadFile(file, next.signal, vi.fn(), create)
    xhr.onload?.()
    await completed
    next.abort()
    expect(xhr.abort).not.toHaveBeenCalled()
  })

  it('does not send invalid files or already cancelled requests', async () => {
    const create = vi.fn()
    await expect(uploadFile(new File([], 'empty.pdf'), controller().signal, vi.fn(), create)).rejects.toThrow('empty')
    const cancel = controller()
    cancel.abort()
    await expect(uploadFile(file, cancel.signal, vi.fn(), create)).rejects.toMatchObject({ name: 'AbortError' })
    expect(create).not.toHaveBeenCalled()
  })

  it('rejects successful responses without a document ID', async () => {
    const { xhr, create } = requestDouble()
    xhr.responseText = '{}'
    const result = uploadFile(file, controller().signal, vi.fn(), create)
    xhr.onload?.()
    await expect(result).rejects.toThrow('document ID')
  })
})

describe('ingest monitoring', () => {
  it('reports processing progress, polls to ready, then loads the real document', async () => {
    const transport = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json({ status: 'running', step: 'reading_pages', progress: 0.4 }))
      .mockResolvedValueOnce(Response.json({ status: 'ready', progress: 1 }))
      .mockResolvedValueOnce(Response.json(doc))
    const onProgress = vi.fn()
    const result = await waitForUpload(doc.doc_id, { signal: controller().signal, transport, intervalMs: 0, onProgress })
    expect(onProgress).toHaveBeenCalledWith('Reading drawing', 0.4)
    expect(result.document).toEqual(doc)
    expect(transport.mock.calls.map(([path]) => path)).toEqual([`/api/docs/${doc.doc_id}/ingest`, `/api/docs/${doc.doc_id}/ingest`, `/api/docs/${doc.doc_id}`])
  })

  it('offers the document as soon as ingest reports readable, then keeps polling to ready', async () => {
    const transport = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json({ status: 'running', step: 'planmap', progress: 0.75, readable: true }))
      .mockResolvedValueOnce(Response.json(doc))
      .mockResolvedValueOnce(Response.json({ status: 'running', step: 'planmap', progress: 0.9, readable: true }))
      .mockResolvedValueOnce(Response.json({ status: 'ready', readable: true }))
      .mockResolvedValueOnce(Response.json(doc))
    const onReadable = vi.fn()
    const result = await waitForUpload(doc.doc_id, { signal: controller().signal, transport, intervalMs: 0, onProgress: vi.fn(), onReadable })
    expect(onReadable).toHaveBeenCalledTimes(1)
    expect(onReadable).toHaveBeenCalledWith(doc)
    expect(result.document).toEqual(doc)
  })

  it('shows which IFC quantities are ready while the 3D view is prepared', async () => {
    const detail = 'The 3D view is still being prepared. Counts and quantities stored in the model are available.'
    const transport = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json({ status: 'running', step: 'ifc_scene', readable: true, detail }))
      .mockResolvedValueOnce(Response.json(doc))
      .mockResolvedValueOnce(Response.json({ status: 'partial', readable: true, detail: 'The 3D view exceeded its memory budget. Counts are available.' }))
      .mockResolvedValueOnce(Response.json(doc))
    const onReadable = vi.fn()
    const result = await waitForUpload(doc.doc_id, { signal: controller().signal, transport, intervalMs: 0, onProgress: vi.fn(), onReadable })
    expect(onReadable).toHaveBeenCalledWith(doc, detail)
    expect(result.note).toContain('memory budget')
  })

  it('uses reason for terminal failure and preserves partial processing notes', async () => {
    await expect(waitForUpload(doc.doc_id, { signal: controller().signal, onProgress: vi.fn(), transport: vi.fn().mockResolvedValue(Response.json({ status: 'failed', reason: 'The IFC file is corrupt.' })) })).rejects.toMatchObject({ message: 'The IFC file is corrupt.', retry: 'upload' })
    const transport = vi.fn().mockResolvedValueOnce(Response.json({ status: 'partial', detail: 'Page image only; no plan map.' })).mockResolvedValueOnce(Response.json(doc))
    await expect(waitForUpload(doc.doc_id, { signal: controller().signal, onProgress: vi.fn(), transport })).resolves.toMatchObject({ document: doc, note: 'Page image only; no plan map.' })
  })

  it('falls back to document polling when ingest is missing, without treating an existing row as ready', async () => {
    const transport = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(null, { status: 404 }))
      .mockResolvedValueOnce(Response.json(doc))
      .mockResolvedValueOnce(new Response(null, { status: 404 }))
      .mockResolvedValueOnce(Response.json(doc))
      .mockResolvedValueOnce(Response.json({ items: [] }))
    const onProgress = vi.fn()
    const result = await waitForUpload(doc.doc_id, { signal: controller().signal, transport, onProgress, intervalMs: 0 })
    expect(result.document).toEqual(doc)
    expect(result.note).toContain('unavailable')
    expect(onProgress).toHaveBeenCalledWith(expect.stringContaining('unavailable'), null)
    expect(transport.mock.calls.map(([path]) => path)).toEqual([`/api/docs/${doc.doc_id}/ingest`, `/api/docs/${doc.doc_id}`, `/api/docs/${doc.doc_id}/planmap/1`, `/api/docs/${doc.doc_id}`, `/api/docs/${doc.doc_id}/planmap/1`])
  })

  it('uses explicit document ingestion state in the fallback', async () => {
    const transport = vi.fn().mockResolvedValueOnce(new Response(null, { status: 501 }))
      .mockResolvedValueOnce(Response.json({ ...doc, ingest: { status: 'running', step: 'Pages', progress: 0.2 } }))
      .mockResolvedValueOnce(Response.json({ ...doc, ingest: { status: 'ready' } }))
    const onProgress = vi.fn()
    await waitForUpload(doc.doc_id, { signal: controller().signal, transport, onProgress, intervalMs: 0 })
    expect(onProgress).toHaveBeenCalledWith('Reading drawing', 0.2)
    expect(transport).toHaveBeenCalledTimes(3)
  })

  it('checks an existing IFC scene without triggering conversion in legacy mode', async () => {
    const transport = vi.fn().mockResolvedValueOnce(new Response(null, { status: 405 }))
      .mockResolvedValueOnce(Response.json({ ...doc, kind: 'ifc' })).mockResolvedValueOnce(Response.json({ items: {} }))
    await waitForUpload(doc.doc_id, { signal: controller().signal, transport, onProgress: vi.fn() })
    expect(transport.mock.calls[2][0]).toBe(`/api/docs/${doc.doc_id}/files/scene.json`)
  })

  it('retains poll retry semantics on server and network errors', async () => {
    for (const transport of [vi.fn().mockResolvedValue(Response.json({ detail: 'Server busy' }, { status: 503 })), vi.fn().mockRejectedValue(new TypeError('offline'))]) {
      await expect(waitForUpload(doc.doc_id, { signal: controller().signal, transport, onProgress: vi.fn() })).rejects.toMatchObject({ retry: 'poll' })
      expect(transport).toHaveBeenCalledTimes(1)
    }
  })

  it('does not call a saved-only document ready', async () => {
    await expect(waitForUpload(doc.doc_id, { signal: controller().signal, onProgress: vi.fn(), transport: vi.fn().mockResolvedValue(Response.json({ status: 'none' })) })).rejects.toThrow('processing is unavailable')
  })

  it('bounds processing time and cancels polling on dialog close', async () => {
    vi.useFakeTimers()
    const transport = vi.fn().mockResolvedValue(Response.json({ status: 'running' }))
    const cancel = controller()
    const result = waitForUpload(doc.doc_id, { signal: cancel.signal, transport, onProgress: vi.fn() })
    const assertion = expect(result).rejects.toMatchObject({ name: 'AbortError' })
    await vi.advanceTimersByTimeAsync(0)
    cancel.abort()
    await assertion
    await vi.advanceTimersByTimeAsync(10_000)
    expect(transport).toHaveBeenCalledTimes(1)
    await expect(waitForUpload(doc.doc_id, { signal: controller().signal, transport, onProgress: vi.fn(), timeoutMs: 0 })).rejects.toMatchObject({ retry: 'poll', message: expect.stringContaining('longer than expected') })
  })
})

describe('findPersistedUpload', () => {
  const file = new File(['abc'], 'plan.pdf', { type: 'application/pdf' })
  const listing = (docs: unknown[]) => (async () => new Response(JSON.stringify({ sources: [{ docs }] }))) as unknown as typeof fetch
  it('recognises a stored upload after an ambiguous failure', async () => {
    const found = await findPersistedUpload(file, Date.now(), listing([{ doc_id: 'uploads__plan-1', title: 'plan', size: 3, updated_at: new Date().toISOString() }]))
    expect(found?.doc_id).toBe('uploads__plan-1')
  })
  it('ignores older or different files', async () => {
    expect(await findPersistedUpload(file, Date.now(), listing([{ doc_id: 'uploads__plan-0', title: 'plan', size: 3, updated_at: '2020-01-01T00:00:00Z' }, { doc_id: 'uploads__x', title: 'plan', size: 9, updated_at: new Date().toISOString() }]))).toBeNull()
  })
})
