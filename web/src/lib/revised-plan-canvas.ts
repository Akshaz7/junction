import { planRevision, type RevisionInput, type RevisionPlan, type Rect } from './revised-plan'

export const REVISED_TITLE = 'Revised plan (generated from 3D edits)'

function median(values: number[]): number {
  const s = [...values].sort((a, b) => a - b)
  return s[Math.floor(s.length / 2)] ?? 255
}

/** Paper colour: median of a thin ring just outside the rect, falling back to the image border. */
function paperColour(data: ImageData, r: Rect, border: string): string {
  const { width: w, height: h } = data
  const rs: number[] = [], gs: number[] = [], bs: number[] = []
  const take = (x: number, y: number) => {
    if (x < 0 || y < 0 || x >= w || y >= h) return
    const i = (y * w + x) * 4
    rs.push(data.data[i]); gs.push(data.data[i + 1]); bs.push(data.data[i + 2])
  }
  const [x0, y0, x1, y1] = r.map(Math.round) as Rect
  for (let x = x0 - 3; x <= x1 + 3; x++) { take(x, y0 - 3); take(x, y1 + 3) }
  for (let y = y0 - 3; y <= y1 + 3; y++) { take(x0 - 3, y); take(x1 + 3, y) }
  return rs.length ? `rgb(${median(rs)},${median(gs)},${median(bs)})` : border
}

function borderColour(data: ImageData): string {
  const { width: w, height: h } = data
  const rs: number[] = [], gs: number[] = [], bs: number[] = []
  const take = (x: number, y: number) => { const i = (y * w + x) * 4; rs.push(data.data[i]); gs.push(data.data[i + 1]); bs.push(data.data[i + 2]) }
  for (let x = 0; x < w; x++) { take(x, 0); take(x, h - 1) }
  for (let y = 0; y < h; y++) { take(0, y); take(w - 1, y) }
  return `rgb(${median(rs)},${median(gs)},${median(bs)})`
}

function cloud(ctx: CanvasRenderingContext2D, [x0, y0, x1, y1]: Rect, bump: number) {
  const edge = (ax: number, ay: number, bx: number, by: number) => {
    const len = Math.hypot(bx - ax, by - ay), n = Math.max(2, Math.round(len / (bump * 1.6)))
    for (let i = 0; i < n; i++) {
      const sx = ax + (bx - ax) * (i / n), sy = ay + (by - ay) * (i / n)
      const ex = ax + (bx - ax) * ((i + 1) / n), ey = ay + (by - ay) * ((i + 1) / n)
      const mx = (sx + ex) / 2, my = (sy + ey) / 2, nx = (by - ay) / len, ny = -(bx - ax) / len
      // Outward bulge (clockwise rect, outward normal is (dy,-dx)/len).
      ctx.quadraticCurveTo(mx + nx * bump, my + ny * bump, ex, ey)
    }
  }
  ctx.beginPath(); ctx.moveTo(x0, y0)
  edge(x0, y0, x1, y0); edge(x1, y0, x1, y1); edge(x1, y1, x0, y1); edge(x0, y1, x0, y0)
  ctx.closePath(); ctx.stroke()
}

function drawTable(ctx: CanvasRenderingContext2D, plan: RevisionPlan, w: number, h: number, k: number, date: string) {
  const fs = 13 * k, rowH = fs * 1.7, padd = 10 * k
  const rows = plan.rows.slice(0, 12)
  const extra = plan.rows.length - rows.length
  const lines = [...rows.map((r) => ({ n: String(r.n), text: r.text })), ...(extra > 0 ? [{ n: '', text: `+${extra} more` }] : [])]
  ctx.font = `${fs}px Helvetica, Arial, sans-serif`
  const title = 'REVISIONS — generated from 3D edits'
  const width = Math.min(w * 0.6, Math.max(...lines.map((l) => ctx.measureText(l.text).width + 40 * k), ctx.measureText(title).width + 2 * padd, 220 * k))
  const height = padd * 2 + rowH * (lines.length + 2)
  const x = w - width - 12 * k, y = h - height - 12 * k
  ctx.fillStyle = 'rgba(255,255,255,0.96)'; ctx.fillRect(x, y, width, height)
  ctx.strokeStyle = '#111'; ctx.lineWidth = 1.5 * k; ctx.strokeRect(x, y, width, height)
  ctx.fillStyle = '#111'; ctx.textBaseline = 'middle'
  ctx.font = `bold ${fs}px Helvetica, Arial, sans-serif`
  ctx.fillText(title, x + padd, y + padd + rowH / 2)
  ctx.beginPath(); ctx.moveTo(x, y + padd + rowH); ctx.lineTo(x + width, y + padd + rowH); ctx.stroke()
  ctx.font = `${fs}px Helvetica, Arial, sans-serif`
  lines.forEach((l, i) => {
    const cy = y + padd + rowH * (i + 1.5)
    ctx.fillStyle = '#c4161c'; ctx.fillText(l.n, x + padd, cy)
    ctx.fillStyle = '#111'; ctx.fillText(l.text, x + padd + 26 * k, cy)
  })
  ctx.fillStyle = '#555'; ctx.font = `${fs * 0.85}px Helvetica, Arial, sans-serif`
  ctx.fillText(`${date} · ${REVISED_TITLE}`, x + padd, y + height - padd - rowH * 0.15)
}

/** Draws the original page into `canvas` and applies the plan (erase, move, clouds, table). */
export function renderRevised(canvas: HTMLCanvasElement, image: CanvasImageSource & { width?: number; height?: number },
  plan: RevisionPlan, opts: { revised: boolean; date?: string } = { revised: true }): void {
  const w = (image as HTMLImageElement).naturalWidth || (image as ImageBitmap).width || 1
  const h = (image as HTMLImageElement).naturalHeight || (image as ImageBitmap).height || 1
  canvas.width = w; canvas.height = h
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  ctx.drawImage(image, 0, 0, w, h)
  if (!opts.revised || !plan.rows.length) return
  const data = ctx.getImageData(0, 0, w, h)
  const border = borderColour(data)
  const k = Math.max(1, w / 1000)
  const original = document.createElement('canvas')
  original.width = w; original.height = h
  original.getContext('2d')!.putImageData(data, 0, 0)
  for (const r of plan.erase) { ctx.fillStyle = paperColour(data, r, border); ctx.fillRect(r[0], r[1], r[2] - r[0], r[3] - r[1]) }
  for (const { src, dst } of plan.copies)
    ctx.drawImage(original, src[0], src[1], src[2] - src[0], src[3] - src[1], dst[0], dst[1], dst[2] - dst[0], dst[3] - dst[1])
  ctx.strokeStyle = '#d4181f'; ctx.lineWidth = 2 * k; ctx.lineJoin = 'round'
  for (const { n, rect } of plan.clouds) {
    cloud(ctx, rect, 4 * k)
    // Numbered triangle tag at the top-left corner of the cloud.
    const s = 9 * k, tx = rect[0], ty = rect[1] - 2 * k
    ctx.fillStyle = '#fff'; ctx.beginPath(); ctx.moveTo(tx, ty - 2 * s); ctx.lineTo(tx - s * 1.1, ty); ctx.lineTo(tx + s * 1.1, ty); ctx.closePath(); ctx.fill(); ctx.stroke()
    ctx.fillStyle = '#d4181f'; ctx.font = `bold ${s * 1.05}px Helvetica, Arial, sans-serif`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
    ctx.fillText(String(n), tx, ty - s * 0.6); ctx.textAlign = 'start'
  }
  drawTable(ctx, plan, w, h, k, opts.date ?? new Date().toISOString().slice(0, 10))
  ctx.fillStyle = '#d4181f'; ctx.font = `bold ${14 * k}px Helvetica, Arial, sans-serif`; ctx.textBaseline = 'top'
  ctx.fillText(REVISED_TITLE.toUpperCase(), 12 * k, 10 * k)
}

export { planRevision }
export type { RevisionInput }
