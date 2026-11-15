import { describe, expect, it } from 'vitest'
import { itemLabel, type SceneManifest } from '../scene'

const items = {
  '3LbNSBzHHBSuzhUUvuwAbw': { kind: 'wall', storey: { name: 'Second Floor' }, node: 'n', usd_name: 'n', bbox_m: null, tag: '3LbNSBzHHBSuzhUUvuwAbw' },
  '1': { kind: 'door', name: 'Entrance door', storey: 'Ground', node: 'n', usd_name: 'n', bbox_m: null },
  '2': { kind: 'beam', storey: null, node: 'n', usd_name: 'n', bbox_m: null, tag: 'beam-002' },
} as unknown as SceneManifest['items']

describe('itemLabel', () => {
  it('never uses a GUID as the label', () => {
    expect(itemLabel({ items }, '3LbNSBzHHBSuzhUUvuwAbw')).toBe('Wall — Second Floor')
  })
  it('prefers the element name and adds the storey', () => {
    expect(itemLabel({ items }, '1')).toBe('Entrance door — Ground')
  })
  it('keeps a readable document tag', () => {
    expect(itemLabel({ items }, '2')).toBe('beam-002')
  })
})
