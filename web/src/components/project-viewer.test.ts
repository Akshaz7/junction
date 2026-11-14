import { afterEach, expect, it, vi } from 'vitest'
import { workspaceApi } from '../lib/api'
import { buildViewerTarget } from './project-viewer'

afterEach(() => vi.restoreAllMocks())

it('builds the same citation object the chat uses, with boxes from the plan map', async () => {
  vi.spyOn(workspaceApi, 'getDocument').mockResolvedValue({ doc_id: 'd', pages: 2, kind: 'raster' } as never)
  vi.spyOn(workspaceApi, 'getPlanMap').mockImplementation(async (_id, page) => ({ doc_id: 'd', page, items: page === 2 ? [{ item_id: 'w1', bbox_px: [1, 2, 3, 4], tag: 'W1' }, { item_id: 'x', bbox_px: null }] : [] }))
  const target = await buildViewerTarget('d', ['w1', 'x'])
  expect(target.mode).toBe('2d')
  expect(target.citation).toMatchObject({ doc_id: 'd', page: 2, kind: 'element', item_ids: ['w1', 'x'] })
  expect(target.answer.evidence.boxes).toEqual([{ item_id: 'w1', page: 2, bbox_px: [1, 2, 3, 4], label: 'W1' }])
  expect(target.answer.evidence.scene.highlight_item_ids).toEqual(['w1', 'x'])
})

it('opens a model without a flat position in 3D, and a plain file with no items in 2D', async () => {
  vi.spyOn(workspaceApi, 'getDocument').mockResolvedValue({ doc_id: 'm', pages: 1, kind: 'ifc' } as never)
  vi.spyOn(workspaceApi, 'getPlanMap').mockRejectedValue(new Error('none'))
  expect((await buildViewerTarget('m', ['wall-1'])).mode).toBe('3d')
  expect((await buildViewerTarget('m', [])).mode).toBe('3d')
  vi.spyOn(workspaceApi, 'getDocument').mockResolvedValue({ doc_id: 'p', pages: 1, kind: 'raster' } as never)
  expect((await buildViewerTarget('p', [])).mode).toBe('2d')
})
