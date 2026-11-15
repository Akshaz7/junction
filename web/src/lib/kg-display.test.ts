import { describe, expect, it } from 'vitest'
import { displayNodes, levelDisplay } from './kg-display'
import type { KgNode } from './kg'

const node = (kind: string, label: string, doc_ids: string[] = []) => ({ id: label, kind, label, doc_ids }) as unknown as KgNode

describe('kg display labels', () => {
  it('hides numeric level codes and placeholder names', () => {
    expect(levelDisplay('-1 fundering')).toBe('Fundering')
    expect(levelDisplay('00 begane grond')).toBe('Begane grond')
    expect(levelDisplay('Undefined')).toBe('Unnamed level')
    expect(levelDisplay('Level 2')).toBe('Level 2')
  })
  it('uses the real file title for a generic file node', () => {
    const out = displayNodes([node('doc', 'Doc', ['d1']), node('room', 'Doc', ['d1'])], new Map([['d1', 'bernts steel structure']]))
    expect(out[0].label).toBe('bernts steel structure')
    expect(out[1].label).toBe('Doc')
  })
})
