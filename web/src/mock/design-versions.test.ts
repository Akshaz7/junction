import { afterEach, describe, expect, it } from 'vitest'
import { demoDocument, handleMockRequest } from './handler'
import { resetDemoVersions } from './design-versions'
import { saveDesignVersion } from '../lib/design-versions'
import { workspaceApi } from '../lib/api'
import { loadRevisionComparison } from '../components/changes-screen'

const doc = demoDocument.doc_id
const get = async (path: string) => (await handleMockRequest(new Request(`http://localhost${path}`)))!

describe('offline demo: save as new version and compare', () => {
  afterEach(() => { resetDemoVersions(); workspaceApi.isDemo = false })

  it('saves through the mock API with no backend, lists it in changes and compares it with the original', async () => {
    workspaceApi.isDemo = true
    expect(await workspaceApi.getChanges()).toEqual([])
    const v = await saveDesignVersion(doc, { removed: ['window-001'], moved: { 'window-002': [1, 0] }, materials: {} })
    expect(v).toMatchObject({ n: 1, parent: 0, created: true, change_id: `dv:${doc}:0-1`, counts: { removed: 1, added: 0, moved: 1, material: 0 } })
    expect(decodeURIComponent(v.compare_url)).toBe(`#/compare?change=dv:${doc}:0-1`)
    expect((await saveDesignVersion(doc, { removed: ['window-001'], moved: { 'window-002': [1, 0] }, materials: {} })).created).toBe(false)
    const v2 = await saveDesignVersion(doc, { removed: [], moved: { 'window-002': [1, 0] }, materials: {} }, { parent: 1 })
    expect([v2.n, v2.parent, v2.counts.added]).toEqual([2, 1, 1])
    await expect(saveDesignVersion(doc, { removed: [], moved: {}, materials: {} })).rejects.toThrow('No edits to save')

    const feed = await workspaceApi.getChanges()
    expect(feed.map((e) => e.id)).toEqual([`dv:${doc}:1-2`, `dv:${doc}:0-1`])
    expect(feed[1].summary).toMatchObject({ index_a: 0, index_b: 1, pair_prefix: `dv:${doc}:`, edited: true, version_a: 'Original' })

    const cmp = await loadRevisionComparison(`dv:${doc}:0-2`, new AbortController().signal)
    expect(cmp.changes.map((c) => [c.action, c.item_id])).toEqual([['moved', 'window-002']])
    expect(cmp.changes[0].sentence).toBe('Item window-002 moved 1.0 m east.')
    expect(cmp.changes[0].v2!.bbox_px![0]).toBeGreaterThan(cmp.changes[0].v1!.bbox_px![0])
    expect(cmp.item_ids).toEqual(['window-002'])
    const first = await loadRevisionComparison(`dv:${doc}:0-1`, new AbortController().signal)
    expect(first.changes.map((c) => c.type)).toEqual(['removed', 'modified'])
    expect(first.generated_for_demo).toBe(true)
  })

  it('lists versions and 404s unknown pairs', async () => {
    await handleMockRequest(new Request(`http://localhost/api/docs/${doc}/versions`, { method: 'POST', body: JSON.stringify({ removed: ['window-001'] }) }))
    const listed = await (await get(`/api/docs/${doc}/versions`)).json()
    expect(listed.versions.map((v: { n: number; label: string }) => v.n)).toEqual([0, 1])
    expect((await get(`/api/changes/${encodeURIComponent(`dv:${doc}:0-7`)}`)).status).toBe(404)
  })
})
