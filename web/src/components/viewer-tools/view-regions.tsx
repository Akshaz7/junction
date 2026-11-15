import { useEffect, useState } from 'react'
import { workspaceApi } from '../../lib/api'
import type { PlanMap } from '../../lib/types'
import './view-regions.css'

type Region = NonNullable<PlanMap['regions']>[number]

export function viewRegionLabel(region: Region): string {
  const name = region.title || ({ plan: 'Plan view', elevation: 'Elevation', section: 'Section', detail: 'Detail', site: 'Site plan', unknown: 'Unresolved view' }[region.view_type ?? 'unknown'])
  const ratio = region.scale?.ratio ?? region.scale?.unverified_printed_ratio
  return `${name}${typeof ratio === 'number' && ratio > 0 ? ` · 1:${ratio}` : ''} · ${region.view_type === 'plan' ? 'used for counts' : 'excluded from plan counts'}`
}

/** Page-space view boundaries sit below item evidence and never intercept it. */
export function ViewRegions({ docId, page, width, height, scale }: { docId: string; page: number; width: number; height: number; scale: number }) {
  const [regions, setRegions] = useState<Region[]>([])
  useEffect(() => {
    const controller = new AbortController()
    setRegions([])
    workspaceApi.getPlanMap(docId, page, controller.signal).then((pm) => {
      if (!controller.signal.aborted) setRegions((pm.regions ?? []).filter((r) => r.view_type && r.bbox.length === 4 && r.bbox.every(Number.isFinite) && r.bbox[2] > r.bbox[0] && r.bbox[3] > r.bbox[1]))
    }).catch(() => {})
    return () => controller.abort()
  }, [docId, page])
  if (!regions.length) return <span className="view-region-status" role="status">No identified view regions on this sheet.</span>
  const font = 11 / Math.max(scale, .001)
  return <svg className="sheet-view-regions" width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-label="Drawing view boundaries">
    {regions.map((region, index) => <g key={region.view_id ?? index} data-view-type={region.view_type}>
      <title>{viewRegionLabel(region)}</title>
      <rect x={region.bbox[0]} y={region.bbox[1]} width={region.bbox[2] - region.bbox[0]} height={region.bbox[3] - region.bbox[1]} vectorEffect="non-scaling-stroke" />
      <text x={region.bbox[0] + font*.5} y={region.bbox[1] + font*1.4} fontSize={font}>{viewRegionLabel(region)}</text>
    </g>)}
  </svg>
}
