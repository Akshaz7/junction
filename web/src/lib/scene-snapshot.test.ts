import { afterEach, describe, expect, it, vi } from 'vitest'
import { applyState, emptyCommandState, readCommandState, type SceneSnapshot } from '../viewer3d/commands'
import type { SceneEvent } from '../viewer3d/liveHighlight'
import { emptyChatEdits, itemIsHidden, reduceSceneEvent } from './scene-edits'
import { applyLiveSceneEvent } from './scene-edit-timing'
import { drawingSnapshot, syncSceneSnapshot } from './scene-snapshot'

function model() {
  let state = emptyCommandState()
  return {
    getCommandState: () => readCommandState(state),
    applyState: vi.fn((snapshot: SceneSnapshot) => { state = applyState(snapshot) }),
    applyCommand: vi.fn(() => { throw new Error('Answer/socket reconciliation must not publish a command') }),
  }
}

afterEach(() => { performance.clearMarks(); performance.clearMeasures() })

describe('immediate drawing and model scene updates', () => {
  it('applies an unlabelled remote hide to both states before an SSE answer or chat refetch exists, within 500 ms', () => {
    const viewer = model()
    let edits = reduceSceneEvent(emptyChatEdits(), {
      type: 'scene.edit', doc_id: 'drawing', op: 'highlight', item_ids: ['a', 'b'], labels: { a: 'W3', b: 'W4' }, edit_id: 'show',
    })
    syncSceneSnapshot(viewer, drawingSnapshot(edits.docs.drawing))
    const hide: SceneEvent = { type: 'scene.edit', doc_id: 'drawing', op: 'hide', item_ids: ['a'], edit_id: 'remote-hide' }
    applyLiveSceneEvent(hide, () => {
      edits = reduceSceneEvent(edits, hide)
      syncSceneSnapshot(viewer, drawingSnapshot(edits.docs.drawing))
    })
    expect(itemIsHidden(edits.docs.drawing, 'a')).toBe(true)
    expect(edits.docs.drawing.tags.a).toBe('W3')
    expect(viewer.getCommandState()).toEqual({ hidden: ['a'], highlighted: { b: 'W4' }, isolated: null })
    expect(viewer.applyCommand).not.toHaveBeenCalled()
    const [timing] = performance.getEntriesByName('scene-edit:remote-hide:receive-to-applied')
    expect(timing).toBeDefined()
    expect(timing.duration).toBeLessThan(500)

    // The global viewer socket and the late answer carry the same edit. Neither
    // should rebuild materials/labels or echo commands back to other devices.
    const calls = viewer.applyState.mock.calls.length
    edits = reduceSceneEvent(edits, { ...hide, labels: { a: 'W3' } })
    syncSceneSnapshot(viewer, drawingSnapshot(edits.docs.drawing))
    expect(viewer.applyState).toHaveBeenCalledTimes(calls)
  })

  it('skips an already-applied socket update regardless of set/map order', () => {
    const viewer = model()
    viewer.applyState({ hidden: ['a', 'b'], highlighted: ['c', 'd'], labels: { c: 'W3', d: 'W4' }, isolated: ['c', 'd'] })
    syncSceneSnapshot(viewer, { hidden: ['b', 'a'], highlighted: ['d', 'c'], labels: { d: 'W4', c: 'W3' }, isolated: ['d', 'c'] })
    expect(viewer.applyState).toHaveBeenCalledOnce()
  })

  it('restores and resets immediately and never lets late hide metadata revert Undo', () => {
    const viewer = model()
    const hide = { type: 'scene.edit' as const, doc_id: 'drawing', op: 'hide' as const, item_ids: ['a'], edit_id: 'hide' }
    let edits = reduceSceneEvent(emptyChatEdits(), hide)
    syncSceneSnapshot(viewer, drawingSnapshot(edits.docs.drawing))
    edits = reduceSceneEvent(edits, { ...hide, op: 'restore', edit_id: 'undo' })
    syncSceneSnapshot(viewer, drawingSnapshot(edits.docs.drawing))
    edits = reduceSceneEvent(edits, { ...hide, labels: { a: 'W3' } })
    syncSceneSnapshot(viewer, drawingSnapshot(edits.docs.drawing))
    expect(viewer.getCommandState().hidden).toEqual([])
    expect(viewer.applyState).toHaveBeenCalledTimes(2)
    edits = reduceSceneEvent(edits, { ...hide, op: 'isolate', edit_id: 'isolate', labels: { a: 'W3' } })
    syncSceneSnapshot(viewer, drawingSnapshot(edits.docs.drawing))
    edits = reduceSceneEvent(edits, { ...hide, op: 'reset', item_ids: [], edit_id: 'reset' })
    syncSceneSnapshot(viewer, drawingSnapshot(edits.docs.drawing))
    expect(viewer.getCommandState()).toEqual({ hidden: [], highlighted: {}, isolated: null })
  })
})
