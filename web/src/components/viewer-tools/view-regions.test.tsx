// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { describe, expect, it, vi } from 'vitest'
import { ViewRegions, viewRegionLabel } from './view-regions'

vi.mock('../../lib/api', () => ({ workspaceApi: { getPlanMap: vi.fn(async () => ({ regions: [
  { bbox: [0, 0, 400, 600], title: 'Ground floor', view_type: 'plan', scale: { ratio: 100 } },
  { bbox: [500, 0, 900, 600], title: 'North', view_type: 'elevation', scale: { ratio: 48 } },
] })) } }))

describe('sheet view regions', () => {
  it('explains a printed ratio even when it has no physical calibration', () => {
    expect(viewRegionLabel({ bbox: [0, 0, 1, 1], view_type: 'plan', scale: { ratio: 64, m_per_px: null } })).toBe('Plan view · 1:64 · used for counts')
    expect(viewRegionLabel({ bbox: [0, 0, 1, 1], view_type: 'unknown' })).toContain('excluded from plan counts')
  })
  it('draws labeled plan and excluded boundaries in page coordinates', async () => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
    const host = document.createElement('div')
    const root = createRoot(host)
    try {
      await act(async () => root.render(<ViewRegions docId="test" page={1} width={1000} height={800} scale={1} />))
      expect(host.querySelector('[aria-label="Drawing view boundaries"]')).toBeTruthy()
      expect(host.textContent).toContain('Ground floor · 1:100 · used for counts')
      expect(host.querySelector('[data-view-type="elevation"] rect')?.getAttribute('x')).toBe('500')
      expect(host.textContent).toContain('North · 1:48 · excluded from plan counts')
    } finally { await act(async () => root.unmount()) }
  })
})
