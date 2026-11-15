/**
 * Measure-tool geometry. All points are page pixels (the plan map's pixel frame);
 * metres come only from the page scale `m_per_px` and are never invented.
 */
export type Pt = [number, number] // page pixels
export interface SnapItem { bbox: [number, number, number, number]; polygon?: Pt[] | null }

const dist2 = (a: Pt, b: Pt) => (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2
const finite = (p: Pt | undefined): p is Pt => !!p && Number.isFinite(p[0]) && Number.isFinite(p[1])

function itemVertices(item: SnapItem): Pt[] {
  const [x0, y0, x1, y1] = item.bbox
  const out: Pt[] = (item.polygon ?? []).filter(finite)
  if ([x0, y0, x1, y1].every(Number.isFinite)) out.push([x0, y0], [x1, y0], [x1, y1], [x0, y1])
  return out
}

function itemEdges(item: SnapItem): [Pt, Pt][] {
  const edges: [Pt, Pt][] = []
  const ring = (pts: Pt[]) => { if (pts.length < 2) return; for (let i = 0; i < pts.length; i++) edges.push([pts[i], pts[(i + 1) % pts.length]]) }
  ring((item.polygon ?? []).filter(finite))
  const [x0, y0, x1, y1] = item.bbox
  if ([x0, y0, x1, y1].every(Number.isFinite)) ring([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
  return edges
}

function closestOnSegment(p: Pt, a: Pt, b: Pt): Pt {
  const dx = b[0] - a[0], dy = b[1] - a[1]
  const len2 = dx * dx + dy * dy
  if (len2 === 0) return [a[0], a[1]]
  const t = Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2))
  return [a[0] + t * dx, a[1] + t * dy]
}

/** Nearest polygon vertex / bbox corner within tolerance, else nearest point on an edge within tolerance, else p. */
export function snapPoint(p: Pt, items: SnapItem[], tolerancePx: number): Pt {
  if (!finite(p) || !(tolerancePx > 0)) return p
  const tol2 = tolerancePx * tolerancePx
  let best: Pt | null = null, bestD = tol2
  for (const item of items) for (const v of itemVertices(item)) {
    const d = dist2(p, v)
    if (d <= bestD) { best = [v[0], v[1]]; bestD = d }
  }
  if (best) return best
  bestD = tol2
  for (const item of items) for (const [a, b] of itemEdges(item)) {
    const q = closestOnSegment(p, a, b)
    const d = dist2(p, q)
    if (d <= bestD) { best = q; bestD = d }
  }
  return best ?? p
}

export function distanceM(a: Pt, b: Pt, mPerPx: number): number {
  return Math.sqrt(dist2(a, b)) * mPerPx
}

/** Shoelace area of a simple polygon, in m² (px² × mPerPx²). Fewer than 3 points → 0. */
export function polygonAreaM2(pts: Pt[], mPerPx: number): number {
  if (pts.length < 3) return 0
  let s = 0
  for (let i = 0; i < pts.length; i++) {
    const [x0, y0] = pts[i], [x1, y1] = pts[(i + 1) % pts.length]
    s += x0 * y1 - x1 * y0
  }
  return Math.abs(s) / 2 * mPerPx * mPerPx
}

export function perimeterM(pts: Pt[], mPerPx: number, closed: boolean): number {
  let total = 0
  for (let i = 1; i < pts.length; i++) total += distanceM(pts[i - 1], pts[i], mPerPx)
  if (closed && pts.length > 2) total += distanceM(pts[pts.length - 1], pts[0], mPerPx)
  return total
}

export function formatM(m: number): string {
  if (!Number.isFinite(m) || m < 0) return '—'
  if (m < 0.01) return '<1 cm'
  return `${m.toFixed(2)} m`
}

export function formatM2(m2: number): string {
  if (!Number.isFinite(m2) || m2 < 0) return '—'
  if (m2 < 0.01) return '<0.01 m²'
  return `${m2.toFixed(2)} m²`
}
