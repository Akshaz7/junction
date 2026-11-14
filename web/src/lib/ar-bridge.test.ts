import { describe, expect, it, vi } from 'vitest'
import { answerTableSelection, arHandler, showOnTable } from './ar-bridge'
import { makeDemoAnswer } from '../mock/handler'

describe('native AR bridge', () => {
  it('sends only contract fields and preserves evidence order', () => {
    const answer = makeDemoAnswer('How many windows are there?')
    answer.evidence.scene.highlight_item_ids = ['window-002', 'window-001']
    const selection = answerTableSelection(answer)!
    const postMessage = vi.fn()
    showOnTable(selection, { webkit: { messageHandlers: { ar: { postMessage } } } })
    expect(postMessage).toHaveBeenCalledExactlyOnceWith({ doc_id: answer.evidence.scene.doc_id, item_ids: ['window-002', 'window-001'] })
    expect(arHandler({})).toBeNull()
    expect(() => showOnTable(selection, {})).not.toThrow()
  })

  it('uses box evidence when scene selections are empty and omits abstentions', () => {
    const answer = makeDemoAnswer('How many windows are there?')
    answer.evidence.scene.highlight_item_ids = []
    expect(answerTableSelection(answer)?.item_ids).toEqual(answer.evidence.boxes.map((box) => box.item_id))
    answer.answer.abstained = true
    expect(answerTableSelection(answer)).toBeNull()
  })
})
