import { describe, expect, it } from 'vitest'
import { readChange, summariseChanges, whereOnSheet } from './change-copy'
import type { Comparison } from './types'

const size = { w: 1000, h: 1000 }
const item = (sentence: string, bbox: [number, number, number, number] = [100, 100, 400, 400]): Comparison['changes'][number] => ({ n: 1, change_id: 'c', type: 'modified', kind: 'region', sentence, v1: null, v2: { item_id: 'i', bbox_px: bbox } })

describe('plain-language change copy', () => {
  it('names notes and sheet references', () => {
    expect(readChange(item('Text added: "53703".'), size).text).toBe('Label "53703" added near the top left of the sheet')
    expect(readChange(item('Text added: "Existing roof joist".'), size).text).toBe('Note added near the top left of the sheet: "Existing roof joist"')
    expect(readChange(item('Text changed from "S100 8" to "S300 4 A100 4C".'), size).small).toBe(true)
    expect(readChange(item('Content added in this region (no text change).', [900, 100, 990, 300]), size).text).toBe('Title block updated (logo, stamp or revision list)')
    expect(readChange(item('Text removed: "9".'), size).kind).toBe('note-removed')
    expect(readChange(item('Text changed from "S100 8" to "A300 2".'), size).text).toBe('Sheet reference changed: S100/8 → A300/2')
    expect(readChange(item('Text changed from "1" to "WI Madison, | #300".'), size).text).toContain('Note edited')
    expect(readChange(item('Text changed from "aaa …" to "bbb …".'), size).text).toContain('Text rewritten')
  })

  it('never shows engine boilerplate and groups tiny linework edits', () => {
    const tiny = readChange(item('Changed region (no text change).', [10, 10, 40, 40]), size)
    const big = readChange(item('Content removed from this region (no text change).', [100, 600, 500, 900]), size)
    expect(tiny.small).toBe(true)
    expect(big.small).toBe(false)
    expect(`${tiny.text}${big.text}`).not.toMatch(/no text change|Changed region/)
    expect(big.text).toBe('Drawing content removed near the bottom left of the sheet')
    expect(whereOnSheet([900, 100, 990, 200], size)).toBe('in the title block')
  })

  it('writes a one-line summary', () => {
    const rows = [readChange(item('Text added: "1".'), size), readChange(item('Text changed from "1" to "2".'), size), readChange(item('Changed region (no text change).', [0, 0, 10, 10]), size)]
    expect(summariseChanges(rows)).toBe('Only minor edits: 3 (callout labels, linework, title block).')
    const mixed = [readChange(item('Text added: "New stair rail".'), size), readChange(item('Changed region (no text change).', [0, 0, 10, 10]), size)]
    expect(summariseChanges(mixed)).toBe('1 note added. Plus 1 minor edit (callout labels, linework, title block).')
  })
})
