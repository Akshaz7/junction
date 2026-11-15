/**
 * One-line hover summaries for plan-map items ("Wall · 10.57 m long · 0.27 m thick").
 * Deterministic: reads only the item's own props/label/bbox. When props carry no size and a
 * scale is known, the bbox gives an approximate size marked with "≈"; without a scale the
 * line is just the kind (plus any name). Nothing is invented.
 */
import { KIND_COLORS, KIND_KEYS, type KindKey } from './kind-colors'

export interface PlanSummaryItem { id: string; kind: string; label?: string | null; props?: Record<string, unknown> | null; bbox: [number, number, number, number] }

const SEP = ' · '
const TEXT_MAX = 60

/** Plan-map kinds whose display name differs from a plain humanised kind. */
const NAMES: Record<string, string> = { wc: 'Toilet', sanitary: 'Toilet', stair: 'Stairs', stair_flight: 'Stairs', stairflight: 'Stairs', text: 'Text' }

function humanise(raw: string): string {
  const s = raw.replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim().toLowerCase()
  return s ? s[0].toUpperCase() + s.slice(1) : ''
}

/** Display name for a kind: bathtub → Bathtub, wc → Toilet, curtain_wall → Curtain wall. */
export function kindName(kind: string | null | undefined): string {
  const k = (kind ?? '').trim().toLowerCase()
  if (NAMES[k]) return NAMES[k]
  if ((KIND_KEYS as readonly string[]).includes(k)) return KIND_COLORS[k as KindKey].label
  return humanise(k) || 'Item'
}

function num(v: unknown): number | null {
  const n = typeof v === 'number' ? v : typeof v === 'string' && v.trim() !== '' ? Number(v) : NaN
  return Number.isFinite(n) ? n : null
}

function pos(v: unknown): number | null {
  const n = num(v)
  return n != null && n > 0 ? n : null
}

function str(v: unknown): string | null {
  if (typeof v === 'number' && Number.isFinite(v)) return String(v)
  if (typeof v !== 'string') return null
  const s = v.replace(/\s+/g, ' ').trim()
  return s || null
}

const m = (v: number) => `${v.toFixed(2)} m`
const m2 = (v: number) => `${v.toFixed(2)} m²`

/** Bbox side lengths in metres, or null without a usable scale. */
function bboxMetres(bbox: PlanSummaryItem['bbox'], mPerPx: number | null | undefined): { w: number; h: number } | null {
  const s = pos(mPerPx)
  if (s == null || !Array.isArray(bbox) || bbox.length < 4) return null
  const [x0, y0, x1, y1] = bbox.map(Number)
  const w = Math.abs(x1 - x0) * s, h = Math.abs(y1 - y0) * s
  if (!Number.isFinite(w) || !Number.isFinite(h) || (w <= 0 && h <= 0)) return null
  return { w, h }
}

function quoted(text: string): string {
  const t = text.length > TEXT_MAX ? `${text.slice(0, TEXT_MAX - 1).trimEnd()}…` : text
  return `“${t}”`
}

/** One short deterministic line from plan-map props; falls back to bbox × mPerPx for size when props lack it; never invents. */
export function planItemSummary(item: PlanSummaryItem, mPerPx?: number | null): string {
  const kind = (item.kind ?? '').trim().toLowerCase()
  const p = item.props ?? {}
  const label = str(item.label)
  const box = bboxMetres(item.bbox, mPerPx)
  const parts: string[] = []

  if (kind === 'text') {
    const role = str(p.role)
    const text = label ?? str(p.text) ?? str(p.content)
    const head = role ? humanise(role) : 'Text'
    return text ? `${head}${SEP}${quoted(text)}` : head
  }

  if (kind === 'room') {
    const number = str(p.number)
    const type = str(p.room_type)
    const name = label ?? str(p.name) ?? (type && type.toLowerCase() !== 'other' ? humanise(type) : null)
    const head = ['Room', number, name].filter(Boolean).join(' ')
    const area = pos(p.area_m2) ?? pos(p.area_m2_label) ?? pos(p.area_m2_geom)
    if (area != null) parts.push(m2(area))
    else if (box) parts.push(`≈ ${box.w.toFixed(2)} × ${box.h.toFixed(2)} m`)
    return [head, ...parts].join(SEP)
  }

  if (kind === 'wall' || kind === 'curtain_wall') {
    const length = pos(p.length_m)
    const thick = pos(p.thickness_m) ?? pos(p.width_m)
    if (length != null) parts.push(`${m(length)} long`)
    else if (box) parts.push(`≈ ${m(Math.max(box.w, box.h))} long`)
    if (thick != null) parts.push(`${m(thick)} thick`)
    // Thickness from a bbox only makes sense for a clearly axis-aligned wall.
    else if (box && length == null && Math.min(box.w, box.h) > 0 && Math.max(box.w, box.h) >= 4 * Math.min(box.w, box.h)) parts.push(`≈ ${m(Math.min(box.w, box.h))} thick`)
    return [kindName(kind), ...parts].join(SEP)
  }

  if (kind === 'door') {
    const double = p.double === true
    const width = pos(p.width_m)
    if (width != null) parts.push(`${m(width)} wide`)
    else if (box) parts.push(`≈ ${m(Math.max(box.w, box.h))} wide`)
    const swing = str(p.swing)?.toLowerCase()
    if (swing === 'cw') parts.push('swings clockwise')
    else if (swing === 'ccw') parts.push('swings anticlockwise')
    return [double ? 'Double door' : 'Door', ...parts].join(SEP)
  }

  if (kind === 'window') {
    const width = pos(p.width_m)
    if (width != null) parts.push(m(width))
    else if (box) parts.push(`≈ ${m(Math.max(box.w, box.h))}`)
    return [kindName(kind), ...parts].join(SEP)
  }

  // Fixtures and anything else: name if the item has one, then the sizes it carries.
  const name = label && label.toLowerCase() !== kindName(kind).toLowerCase() ? label : null
  const head = name ? `${kindName(kind)} ${name}` : kindName(kind)
  const length = pos(p.length_m), width = pos(p.width_m), area = pos(p.area_m2)
  if (length != null && width != null) parts.push(`${length.toFixed(2)} × ${width.toFixed(2)} m`)
  else if (length != null) parts.push(`${m(length)} long`)
  else if (width != null) parts.push(`${m(width)} wide`)
  if (area != null) parts.push(m2(area))
  if (!parts.length && box) parts.push(`≈ ${box.w.toFixed(2)} × ${box.h.toFixed(2)} m`)
  return [head, ...parts].join(SEP)
}
