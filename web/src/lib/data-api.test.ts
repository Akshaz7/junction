import { describe, expect, it, vi } from 'vitest'
import { WorkspaceApi } from './api'

describe('document uploads and artifacts', () => {
  it('posts the original file as multipart without overriding its boundary', async () => {
    const receipt = { doc_id: 'uploads__floor-plan', status: 'ingesting', detail: '' }
    const transport = vi.fn<typeof fetch>().mockResolvedValue(Response.json(receipt))
    const api = new WorkspaceApi('real', transport)
    const file = new File(['drawing bytes'], 'floor-plan.png', { type: 'image/png' })
    expect(await api.uploadDocument(file)).toEqual(receipt)
    const [path, init] = transport.mock.calls[0]
    expect(path).toBe('/api/upload')
    expect(init?.method).toBe('POST')
    expect(init?.headers).toBeUndefined()
    const part = (init?.body as FormData).get('file') as File
    expect(part.name).toBe(file.name)
    expect(part.type).toBe(file.type)
    expect(await part.text()).toBe('drawing bytes')
  })

  it('reads running and terminal ingestion states with the cancellation signal', async () => {
    const running = { status: 'running', stages: [], detail: '' }
    const partial = { status: 'partial', stages: [{ stage: 'pages', ok: true, s: 0.1 }], detail: 'No plan map yet' }
    const transport = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(running)).mockResolvedValueOnce(Response.json(partial))
    const api = new WorkspaceApi('real', transport)
    const signal = new AbortController().signal
    expect(await api.getIngestStatus('uploads__plan', signal)).toEqual(running)
    expect(await api.getIngestStatus('uploads__plan', signal)).toEqual(partial)
    expect(transport.mock.calls[0]).toEqual(['/api/docs/uploads__plan/ingest', { signal }])
  })

  it('checks an existing scene without triggering scene generation; only 404 means missing', async () => {
    const transport = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json({ glb: 'scene.glb' }))
      .mockResolvedValueOnce(Response.json({ status: 'not_built', detail: 'scene not available' }, { status: 404 }))
      .mockImplementation(async () => Response.json({ detail: 'Server unavailable' }, { status: 503 }))
    const api = new WorkspaceApi('real', transport)
    const signal = new AbortController().signal
    expect(await api.hasScene('ifc__example', signal)).toBe(true)
    expect(await api.hasScene('ifc__example', signal)).toBe(false)
    await expect(api.hasScene('ifc__example', signal)).rejects.toThrow('Server unavailable')
    expect(transport.mock.calls.every(([path]) => path === '/api/docs/ifc__example/files/scene.json')).toBe(true)
  })

  it('surfaces upload failures without switching to fabricated offline data', async () => {
    const api = new WorkspaceApi('auto', vi.fn<typeof fetch>().mockResolvedValue(Response.json({ detail: 'database unavailable' }, { status: 503 })))
    await expect(api.uploadDocument(new File(['plan'], 'plan.pdf'))).rejects.toThrow('database unavailable')
    expect(api.isDemo).toBe(false)
  })
})
