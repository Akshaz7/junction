import { thumbLayout, shortVersion, usableBox, type Bbox, type Size } from './sheet-compare'

export type ExportItem = { n: number; kind: 'added' | 'removed' | 'edited'; text: string; before: string | null; after: string | null }
export type ExportInput = { name: string; prev: { label: string; src: string | null }; curr: { label: string; src: string | null }; size: Size; changes: { n: number; kind: ExportItem['kind']; text: string; bbox: Bbox | null }[] }

const esc = (value: string) => value.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!)
const colour = { added: '#367c48', removed: '#ca482a', edited: '#d86b2b' }

/** A standalone page: the numbered list, each change with its before and after crop. No scripts, no remote files. */
export function buildExportHtml(title: string, prevLabel: string, currLabel: string, items: ExportItem[], generatedAt = new Date()): string {
  const rows = items.map((i) => `<tr><td class="n" style="background:${colour[i.kind]}">${i.n}</td><td>${i.before ? `<img src="${i.before}" alt="Version before, change ${i.n}">` : '<span class="none">No image</span>'}</td><td>${i.after ? `<img src="${i.after}" alt="Version after, change ${i.n}">` : '<span class="none">No image</span>'}</td><td>${esc(i.text)}</td></tr>`).join('\n')
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>${esc(title)}</title><style>
body{font:14px/1.45 system-ui,sans-serif;margin:32px;color:#1a1a1a}h1{font-size:18px;margin:0 0 4px}p.meta{color:#666;margin:0 0 20px}
table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #ddd;padding:8px;vertical-align:top;text-align:left}th{font-size:12px;color:#666;font-weight:500}
td.n{width:22px;color:#fff;text-align:center;font-weight:600;border-radius:50%}img{width:236px;height:136px;border:1px solid #ddd;display:block}.none{color:#999}
</style></head><body><h1>${esc(title)}</h1><p class="meta">${esc(prevLabel)} to ${esc(currLabel)} · ${items.length} ${items.length === 1 ? 'change' : 'changes'} · exported ${generatedAt.toISOString().slice(0, 10)}</p>
<table><thead><tr><th></th><th>${esc(shortVersion(prevLabel))}</th><th>${esc(shortVersion(currLabel))}</th><th>What changed</th></tr></thead><tbody>
${rows}
</tbody></table></body></html>`
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image(); img.crossOrigin = 'anonymous'
    img.onload = () => resolve(img); img.onerror = () => reject(new Error('A sheet image could not be loaded for the export.'))
    img.src = src
  })
}

/** Crop the same window the reading thumbnail shows, at 2x. */
export function cropThumb(img: HTMLImageElement, bbox: Bbox, size: Size): string | null {
  const t = thumbLayout(bbox, size)
  const canvas = document.createElement('canvas'); canvas.width = 236; canvas.height = 136
  const ctx = canvas.getContext('2d')
  if (!ctx) return null
  ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, 236, 136)
  const sx = -t.left / t.width * img.naturalWidth, sy = -t.top / t.height * img.naturalHeight
  const sw = 118 / t.width * img.naturalWidth, sh = 68 / t.height * img.naturalHeight
  ctx.drawImage(img, sx, sy, sw, sh, 0, 0, 236, 136)
  return canvas.toDataURL('image/png')
}

export async function downloadReadings(input: ExportInput): Promise<void> {
  const [a, b] = await Promise.all([input.prev.src ? loadImage(input.prev.src).catch(() => null) : null, input.curr.src ? loadImage(input.curr.src).catch(() => null) : null])
  const items: ExportItem[] = input.changes.map((c) => ({ n: c.n, kind: c.kind, text: c.text,
    before: a && usableBox(c.bbox, input.size) ? cropThumb(a, c.bbox, input.size) : null, after: b && usableBox(c.bbox, input.size) ? cropThumb(b, c.bbox, input.size) : null }))
  const html = buildExportHtml(`Changes: ${input.name}`, input.prev.label, input.curr.label, items)
  const url = URL.createObjectURL(new Blob([html], { type: 'text/html' }))
  const link = document.createElement('a'); link.href = url; link.download = `${input.name.replace(/[^\w.-]+/g, '-')}-changes.html`; link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
