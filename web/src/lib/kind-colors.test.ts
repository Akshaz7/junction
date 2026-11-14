import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { KIND_COLORS, KIND_KEYS, kindColor, kindColorsJson, kindCounts, kindFromItemId, kindKey } from './kind-colors'

describe('kind colours', () => {
  it('has ten distinct colours', () => {
    expect(new Set(KIND_KEYS.map((key) => KIND_COLORS[key].color)).size).toBe(10)
  })
  it('maps aliases and unknown kinds', () => {
    expect(kindKey('curtain_wall')).toBe('wall')
    expect(kindKey('furniture')).toBe('other')
    expect(kindColor(null)).toBe(KIND_COLORS.other.color)
    expect(kindFromItemId('window-007')).toBe('window')
    expect(kindFromItemId('2O2Fr$t4X7Zf8NOew3FLOH')).toBeNull()
  })
  it('counts in first-seen order', () => {
    expect(kindCounts(['window', 'door', 'window'])).toEqual([{ key: 'window', count: 2 }, { key: 'door', count: 1 }])
  })
  it('public/kind-colors.json mirrors the table', () => {
    expect(readFileSync(new URL('../../public/kind-colors.json', import.meta.url), 'utf8')).toBe(kindColorsJson())
  })
})
