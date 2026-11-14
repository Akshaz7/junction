import { describe, expect, it } from 'vitest'
import { makeDemoAnswer } from '../mock/handler'
import { answerSceneEvents, answerTags, emptyChatEdits, itemIsHidden, reduceSceneEvent } from './scene-edits'

describe('chat drawing edit layer', () => {
  it('deduplicates SSE answers and their socket echoes without reverting a later hide', () => {
    const answer = makeDemoAnswer('show me all the windows')
    answer.answer.abstained = false
    answer.evidence.scene.commands = [{ op: 'highlight', item_ids: ['window-001', 'window-002'], labels: { 'window-001': 'W1', 'window-002': 'W2' } }]
    const [event] = answerSceneEvents(answer)
    const selected = reduceSceneEvent(emptyChatEdits(), event)
    const hidden = reduceSceneEvent(selected, { type: 'scene.edit', doc_id: event.doc_id, op: 'hide', item_ids: ['window-001'], edit_id: 'hide-1' })
    expect(reduceSceneEvent(hidden, event)).toBe(hidden)
    expect(itemIsHidden(hidden.docs[event.doc_id], 'window-001')).toBe(true)
    expect(hidden.docs[event.doc_id].state.highlighted.has('window-001')).toBe(false)
    expect(hidden.docs[event.doc_id].tags['window-001']).toBe('W1')
  })

  it('replaces edits with a reconnect snapshot and preserves stable tags through undo/reset', () => {
    const doc_id = 'drawing'
    const selected = reduceSceneEvent(emptyChatEdits(), { type: 'scene.edit', doc_id, op: 'isolate', item_ids: ['a'], labels: { a: 'W3' } })
    expect(itemIsHidden(selected.docs[doc_id], 'b')).toBe(true)
    const snapshot = reduceSceneEvent(selected, { type: 'scene.state', doc_id, hidden: ['a'], highlighted: [], labels: {}, isolated: null })
    expect(itemIsHidden(snapshot.docs[doc_id], 'a')).toBe(true)
    expect(itemIsHidden(snapshot.docs[doc_id], 'b')).toBe(false)
    const reset = reduceSceneEvent(snapshot, { type: 'scene.edit', doc_id, op: 'reset', item_ids: [] })
    expect(itemIsHidden(reset.docs[doc_id], 'a')).toBe(false)
    expect(reset.docs[doc_id].tags.a).toBe('W3')
    expect(reset.docs[doc_id].state.highlighted.size).toBe(0)
  })

  it('accepts tag metadata from an SSE hide answer after the stripped socket echo', () => {
    const event = { type: 'scene.edit' as const, doc_id: 'drawing', op: 'hide' as const, item_ids: ['a'], edit_id: 'first-hide' }
    const hidden = reduceSceneEvent(emptyChatEdits(), event)
    const restored = reduceSceneEvent(hidden, { ...event, op: 'restore', edit_id: 'undo' })
    const enriched = reduceSceneEvent(restored, { ...event, labels: { a: 'W3' } })
    expect(enriched.docs.drawing.tags.a).toBe('W3')
    expect(itemIsHidden(enriched.docs.drawing, 'a')).toBe(false)
  })

  it('keeps tags in reading order, scopes state by document, and ignores abstained commands', () => {
    const answer = makeDemoAnswer('show windows')
    answer.answer.abstained = false
    answer.evidence.scene.commands = [{ op: 'highlight', item_ids: ['ten', 'two'], labels: { ten: 'W10', two: 'W2' } }]
    expect(answerTags(answer).map((item) => item.tag)).toEqual(['W2', 'W10'])
    const layer = answerSceneEvents(answer).reduce(reduceSceneEvent, emptyChatEdits())
    expect(itemIsHidden(layer.docs.other, 'two')).toBe(false)
    answer.answer.abstained = true
    expect(answerSceneEvents(answer)).toEqual([])
  })
})
