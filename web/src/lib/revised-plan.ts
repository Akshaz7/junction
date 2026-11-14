/** Pure planning for the "Revised plan" (generated from 3D edits). No DOM here. */
export type Rect = [number, number, number, number]

export interface RevisionItem {
  item_id: string
  kind?: string | null
  label?: string | null
  tag?: string | null
  bbox_px: Rect | null
}
export interface RevisionInput {
  size: { w: number; h: number }
  items: RevisionItem[]
  removed: ReadonlySet<string> | readonly string[]
  /** Offset in metres (x east, z south) as applied in 3D. */
  moved: Record<string, [number, number]>
  /** metres per pixel of the page; moves are skipped without it. */
  mPerPx: number | null | undefined
}
export interface RevisionPlan {
  erase: Rect[]
  copies: { src: Rect; dst: Rect }[]
  clouds: { n: number; rect: Rect }[]
  rows: { n: number; text: string }[]
}

export const ERASE_PAD = 2
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v))

export function friendlyName(item: RevisionItem): string {
  const kind = (item.kind ?? 'item').replace(/[_-]+/g, ' ')
  const cap = kind.charAt(0).toUpperCase() + kind.slice(1)
  const id = item.tag || item.label
  return id ? `${cap} ${id}` : cap
}

export function describeMove(dx: number, dz: number): string {
  const part = (v: number, pos: string, neg: string) => `${Math.abs(v).toFixed(1)} m ${v > 0 ? pos : neg}`
  const parts: string[] = []
  if (Math.abs(dx) >= 0.05) parts.push(part(dx, 'east', 'west'))
  if (Math.abs(dz) >= 0.05) parts.push(part(dz, 'south', 'north'))
  return parts.join(', ')
}

const pad = (r: Rect, p: number, size: { w: number; h: number }): Rect => [
  clamp(Math.floor(r[0]) - p, 0, size.w), clamp(Math.floor(r[1]) - p, 0, size.h),
  clamp(Math.ceil(r[2]) + p, 0, size.w), clamp(Math.ceil(r[3]) + p, 0, size.h)]
const union = (a: Rect, b: Rect): Rect => [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[2], b[2]), Math.max(a[3], b[3])]

export function planRevision(input: RevisionInput): RevisionPlan {
  const removed = new Set(input.removed)
  const plan: RevisionPlan = { erase: [], copies: [], clouds: [], rows: [] }
  let n = 0
  for (const item of input.items) {
    const box = item.bbox_px
    if (!box) continue
    const gone = removed.has(item.item_id)
    const move = input.mPerPx && input.mPerPx > 0 ? input.moved[item.item_id] : undefined
    const text = move ? describeMove(move[0], move[1]) : ''
    if (!gone && !text) continue
    n += 1
    const src = pad(box, 0, input.size)
    plan.erase.push(pad(box, ERASE_PAD, input.size))
    if (gone) {
      plan.clouds.push({ n, rect: pad(box, 4, input.size) })
      plan.rows.push({ n, text: `${friendlyName(item)} removed` })
    } else {
      const k = 1 / input.mPerPx!
      const dst = pad([box[0] + move![0] * k, box[1] + move![1] * k, box[2] + move![0] * k, box[3] + move![1] * k], 0, input.size)
      plan.copies.push({ src, dst })
      plan.clouds.push({ n, rect: pad(union(box, [dst[0], dst[1], dst[2], dst[3]]), 4, input.size) })
      plan.rows.push({ n, text: `${friendlyName(item)} moved ${text}` })
    }
  }
  return plan
}
