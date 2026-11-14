import { describe, expect, it, vi } from 'vitest'
import { editSnapshot, hasEdits, ownsId, pairId, pairOf, saveDesignVersion, savedMessage, versionOptions, type PairableEntry } from './design-versions'
import { readChange, summariseChanges } from './change-copy'
import type { Comparison } from './types'

const doc = 'ifc_bench__ac20-arc'
const prefix = `dv:${doc}:`
const entries: PairableEntry[] = [
  { id: `${prefix}0-1`, summary: { index_a: 0, index_b: 1, version_a: 'Original', version_b: 'Edited version 1 · 2026-11-14', pair_prefix: prefix } },
  { id: `${prefix}1-2`, summary: { index_a: 1, index_b: 2, version_a: 'Edited version 1 · 2026-11-14', version_b: 'Edited version 2 · 2026-11-14', pair_prefix: prefix } },
]

describe('design versions', () => {
  it('snapshots the edited design: hidden items are removed, moves and materials kept', () => {
    const s = editSnapshot(['b', 'a', 'a'], { moveDelta: { w: [1, 0] }, materials: { wall: 'Glass' } })
    expect(s).toEqual({ removed: ['a', 'b'], moved: { w: [1, 0] }, materials: { wall: 'Glass' } })
    expect(hasEdits(s)).toBe(true)
    expect(hasEdits(editSnapshot([], {}))).toBe(false)
  })

  it('posts the snapshot with its parent version and reports what was saved', async () => {
    const saved = { doc_id: doc, n: 2, parent: 1, label: 'Edited version 2 · 2026-11-14', created: true, change_id: `${prefix}1-2`,
      compare_url: `#/compare?change=${prefix}1-2`, n_changes: 2, counts: { removed: 1, added: 0, moved: 1, material: 0 } }
    const transport = vi.fn(async () => Response.json(saved, { status: 201 }))
    const v = await saveDesignVersion(doc, { removed: ['d'], moved: { w: [1, 0] }, materials: {} }, { parent: 1, chatId: 'c1' }, transport as unknown as typeof fetch)
    const [url, init] = transport.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe(`/api/docs/${doc}/versions`)
    expect(JSON.parse(String(init.body))).toEqual({ removed: ['d'], moved: { w: [1, 0] }, materials: {}, parent: 1, chat_id: 'c1' })
    expect(savedMessage(v)).toBe('Saved as Edited version 2 (1 removed, 1 moved).')
    const refuse = vi.fn(async () => Response.json({ detail: 'No edits to save: remove or move an item first.' }, { status: 400 }))
    await expect(saveDesignVersion(doc, { removed: [], moved: {}, materials: {} }, {}, refuse as unknown as typeof fetch)).rejects.toThrow('No edits to save')
  })

  it('offers every version and builds an id for any two of them', () => {
    expect(versionOptions(entries)).toEqual([
      { index: 0, label: 'Original' }, { index: 1, label: 'Edited version 1 · 2026-11-14' }, { index: 2, label: 'Edited version 2 · 2026-11-14' }])
    expect(pairId(entries, 1, 2)).toBe(`${prefix}1-2`)        // the feed entry itself
    expect(pairId(entries, 0, 2)).toBe(`${prefix}0-2`)        // any other pair
    expect(pairOf(entries, `${prefix}0-2`)).toEqual({ a: 0, b: 2 })
    expect(pairOf(entries, `${prefix}0-1`)).toEqual({ a: 0, b: 1 })
    expect(pairOf(entries, 'ser:other:1-2')).toBeNull()
    expect(ownsId(entries, `${prefix}0-2`)).toBe(true)
    expect(ownsId(entries, 'ser:other:1')).toBe(false)
    // Fixed-pair feeds (no version numbers) are not freely pairable.
    expect(versionOptions([{ id: 'upl:x', summary: { version_a: 'Version 3', version_b: 'Uploaded version' } }])).toEqual([])
    expect(versionOptions([...entries, { id: 'upl:x', summary: { version_a: 'Version 3', version_b: 'Uploaded version' } }])).toEqual([])
  })

  it('reads edit changes as exact item changes, never as title block or region guesses', () => {
    const change = (action: 'removed' | 'moved', sentence: string): Comparison['changes'][number] => ({ n: 1, change_id: 'c1', type: action === 'removed' ? 'removed' : 'modified',
      kind: 'door', sentence, edit: true, action, item_id: 'x', tag: 'D30', v1: { item_id: 'x', bbox_px: [950, 10, 990, 20] }, v2: null })
    const size = { w: 1000, h: 1000 }
    const r = readChange(change('removed', 'Door D30 (Tür-015) was removed.'), size)
    expect(r).toMatchObject({ text: 'Door D30 (Tür-015) was removed.', small: false, kind: 'graphic-removed' })
    const m = readChange(change('moved', 'Window W81 moved 1.0 m east.'), size)
    expect(summariseChanges([r, m])).toBe('1 item removed, 1 item moved.')
  })
})
