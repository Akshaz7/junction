import type { Bbox } from './types'

export interface PickBox { id: string; bbox: Bbox }

/**
 * Inside an aggregate highlight (one box covering several items), pick the item under the click:
 * the smallest candidate whose box, grown by `tolerance` page pixels, contains the point.
 * Returns null when nothing is hit so the caller falls back to the aggregate.
 */
export function pickItemAt(point: [number, number], candidates: PickBox[], allowed: string[], tolerance = 0): string | null {
  const allow = new Set(allowed)
  let best: { id: string; area: number; gap: number } | null = null
  for (const { id, bbox } of candidates) {
    if (!allow.has(id) || bbox.length !== 4 || !bbox.every(Number.isFinite)) continue
    const [x0, y0, x1, y1] = bbox
    if (point[0] < x0 - tolerance || point[0] > x1 + tolerance || point[1] < y0 - tolerance || point[1] > y1 + tolerance) continue
    const gap = Math.max(x0 - point[0], point[0] - x1, y0 - point[1], point[1] - y1, 0)
    const area = (x1 - x0) * (y1 - y0)
    if (!best || gap < best.gap || (gap === best.gap && area < best.area)) best = { id, area, gap }
  }
  return best?.id ?? null
}

/** A plan-map item as the 2D viewer knows it (page pixels). */
export interface PlanPickItem { id: string; kind: string; bbox: Bbox; polygon?: [number, number][] | null; role?: string | null }

function rankOf(kind: string): number {
  if (kind === 'wall') return 1
  if (kind === 'text') return 2
  if (kind === 'room') return 3
  return 0
}

/** Even-odd ray cast. */
function insidePolygon(px: number, py: number, poly: [number, number][]): boolean {
  let inside = false
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const xi = poly[i][0], yi = poly[i][1], xj = poly[j][0], yj = poly[j][1]
    if ((yi > py) !== (yj > py) && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) inside = !inside
  }
  return inside
}

/** Smallest distance from the point to any polygon edge (closing edge included). */
function edgeDistance(px: number, py: number, poly: [number, number][]): number {
  let best = Infinity
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const ax = poly[j][0], ay = poly[j][1], bx = poly[i][0], by = poly[i][1]
    const dx = bx - ax, dy = by - ay
    const len2 = dx * dx + dy * dy
    let t = len2 > 0 ? ((px - ax) * dx + (py - ay) * dy) / len2 : 0
    if (t < 0) t = 0
    else if (t > 1) t = 1
    const ex = ax + t * dx - px, ey = ay + t * dy - py
    const d2 = ex * ex + ey * ey
    if (d2 < best) best = d2
  }
  return Math.sqrt(best)
}

function polygonArea(poly: [number, number][]): number {
  let s = 0
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) s += poly[j][0] * poly[i][1] - poly[i][0] * poly[j][1]
  return Math.abs(s) / 2
}

/**
 * Item under `point` (page pixels), or null. `tolerance` is in page pixels (caller passes ~6px / zoom).
 * Ranking (lower wins): fixtures/doors/windows/etc. < walls < text < rooms; then smallest gap, then smallest area.
 * Walls and rooms use their polygon when present (a wall's bbox can be L-shaped and cover half a room).
 * Text with role 'room_label' is skipped so the room under it is picked.
 */
export function pickPlanItem(point: [number, number], items: PlanPickItem[], tolerance = 0): string | null {
  const px = point[0], py = point[1]
  const tol = Number.isFinite(tolerance) && tolerance > 0 ? tolerance : 0
  let bestId: string | null = null
  let bestRank = Infinity, bestGap = Infinity, bestArea = Infinity
  for (let k = 0; k < items.length; k++) {
    const it = items[k]
    const b = it.bbox
    if (!b || b.length !== 4) continue
    const x0 = b[0], y0 = b[1], x1 = b[2], y1 = b[3]
    if (!Number.isFinite(x0) || !Number.isFinite(y0) || !Number.isFinite(x1) || !Number.isFinite(y1)) continue
    const kind = it.kind
    if (kind === 'text' && it.role === 'room_label') continue
    const rank = rankOf(kind)
    if (rank > bestRank) continue
    const poly = it.polygon && it.polygon.length >= 3 ? it.polygon : null
    const grow = rank === 3 ? 0 : tol
    // Cheap bbox reject (rooms: no tolerance).
    if (px < x0 - grow || px > x1 + grow || py < y0 - grow || py > y1 + grow) continue
    let gap: number
    let area: number
    if (rank === 3) {
      if (poly && !insidePolygon(px, py, poly)) continue
      gap = 0
      area = poly ? polygonArea(poly) : (x1 - x0) * (y1 - y0)
    } else if (rank === 1 && poly) {
      if (insidePolygon(px, py, poly)) gap = 0
      else {
        gap = edgeDistance(px, py, poly)
        if (gap > tol) continue
      }
      area = polygonArea(poly)
    } else {
      gap = Math.max(x0 - px, px - x1, y0 - py, py - y1, 0)
      area = (x1 - x0) * (y1 - y0)
    }
    if (rank < bestRank || gap < bestGap || (gap === bestGap && area < bestArea)) {
      bestId = it.id; bestRank = rank; bestGap = gap; bestArea = area
    }
  }
  return bestId
}
