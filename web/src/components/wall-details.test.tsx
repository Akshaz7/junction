// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it } from 'vitest'
import { WallDetails } from './wall-details'
import { wallAskHref, type WallDetails as Details } from '../lib/wall-details'
import { buildItemDetails } from '../viewer3d/identify'
import type { SceneManifest } from '../viewer3d/scene'

const wall: Details = { status: 'Estimate', classification: 'Internal', length_m: 4, thickness_m: .2,
  height_m: 2.7, height_source: 'assumed default', storey: 'Ground', opening_count: 1,
  faces: [{ label: 'Face A', gross_m2: 10.8, opening_m2: 2.1, net_m2: 8.7 },
    { label: 'Face B', gross_m2: 10.8, opening_m2: 2.1, net_m2: 8.7 }], method: '2D wall outline × height', notes: ['Door-width prior scale.'] }

it('renders both faces and prominently labels assumed height and status', async () => {
  const host = document.createElement('div')
  const root = createRoot(host)
  await act(async () => root.render(<WallDetails wall={wall} />))
  for (const text of ['Estimate', 'Internal', '4.00 m', '0.20 m', '2.70 m', 'assumed default', 'Face A', 'Face B', '10.80 m²', '2.10 m²', '8.70 m²', '1 opening', wall.method]) expect(host.textContent).toContain(text)
  expect(host.querySelectorAll('.wall-detail-face')).toHaveLength(2)
  await act(async () => root.unmount())
})

it('joins wall measurements without showing the misleading unavailable size fallback', () => {
  const scene = { doc_id: 'demo', items: { w: { kind: 'wall', storey: 'Ground' } } } as unknown as SceneManifest
  const card = buildItemDetails(scene, 'w', { item_id: 'w', wall_details: wall })!
  expect(card.wall).toEqual(wall)
  expect(card.fields.some((f) => f.label === 'Size')).toBe(false)
})

it('preserves drawing and wall reference in the ask link', () => {
  const params = new URLSearchParams(wallAskHref('drawing / one', 'WL 12').split('?')[1])
  expect(params.get('doc')).toBe('drawing / one')
  expect(params.get('question')).toContain('wall WL 12')
})
