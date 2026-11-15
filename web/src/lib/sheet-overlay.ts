import type { Answer, Bbox, Document } from './types'

export type XY = [number, number]
export type Matrix = [[number, number, number], [number, number, number]]
export type SheetSize = { w: number; h: number }
export type Alignment = {
  pair_key?: string; status: 'aligned' | 'manual' | 'needs_manual'; matrix: Matrix | null; method: string | null
  anchor_count: number; candidate_count: number; residual_px: number | null; residual_mm: number | null; detail: string
  anchors: { label: string; base: XY; overlay: XY; base_bbox?: Bbox | null }[]; base_image: SheetSize; overlay_image: SheetSize
}
export type OverlayDoc = Document & { project?: string; floor?: string; storey?: string; folder?: string; discipline?: string; subdiscipline?: string }

const disciplines = [
  { name: 'Ventilation', pattern: /ventilation|hvac|ilmanvaihto|lüftung|ventilasjon|\blvi\b/, color: '#166ed1' },
  { name: 'Electrical', pattern: /electrical|electric|sähkö|elektro|\belplan/, color: '#a55e29' },
  { name: 'Plumbing', pattern: /plumbing|water|drain|viemäri|sanitär|vvs/, color: '#0f766e' },
  { name: 'Structure', pattern: /structur|rakenne|tragwerk|konstruktion/, color: '#854a9b' },
  { name: 'Fire protection', pattern: /fire|sprinkler|palo|brand/, color: '#b14142' },
  { name: 'Architecture', pattern: /architect|floor.?plan|pohja|grundriss|planritning|\bark\b/, color: '#536153' },
]
export function discipline(doc: OverlayDoc) {
  const text = `${doc.subdiscipline || ''} ${doc.discipline || ''} ${doc.title}`.toLowerCase()
  return disciplines.find((d) => d.pattern.test(text)) ?? { name: doc.subdiscipline || doc.discipline || 'Drawing', color: '#166ed1' }
}

/** Explicit metadata wins; no assumption that two sheets in one dataset share a floor. */
export function rankOverlaySheets(base: OverlayDoc, docs: OverlayDoc[]) {
  const score = (d: OverlayDoc) => (base.project && d.project === base.project ? 4 : 0) +
    ((base.floor || base.storey) && (d.floor || d.storey) === (base.floor || base.storey) ? 2 : 0) +
    (base.folder && d.folder === base.folder ? 1 : 0)
  return docs.filter((d) => d.doc_id !== base.doc_id && d.pages > 0 && d.kind !== 'ifc')
    .sort((a, b) => score(b) - score(a) || a.title.localeCompare(b.title))
}

export function overlayRequest(question: string, docs: OverlayDoc[], selected: OverlayDoc[]) {
  if (!/\boverlay\b|superimpose|päällekkäin|überlagern|överlagra/i.test(question)) return null
  const candidates = docs.filter((d) => d.pages > 0 && d.kind !== 'ifc')
  const [topText, underText = ''] = question.toLowerCase().split(/\s+(?:on(?:to)?|over|above)\s+(?:the\s+)?/, 2)
  const under = disciplines.find((d) => d.pattern.test(underText))
  const wanted = disciplines.find((d) => d.pattern.test(topText))
  const baseChoices = candidates.filter((d) => under && discipline(d).name === under.name)
  const base = selected.find((d) => under && discipline(d).name === under.name) ??
    (baseChoices.length === 1 ? baseChoices[0] : null) ?? selected[0] ?? candidates.find((d) => discipline(d).name === 'Architecture') ?? candidates[0]
  if (!base) return null
  const ranked = rankOverlaySheets(base, candidates)
  // Ambiguous discipline requests open the picker, rather than silently selecting another floor.
  const matches = ranked.filter((d) => wanted && discipline(d).name === wanted.name)
  const overlay = selected.find((d) => d.doc_id !== base.doc_id && (!wanted || discipline(d).name === wanted.name)) ?? (matches.length === 1 ? matches[0] : null)
  return { base, overlay }
}

export function overlayActionAnswer(question: string, base: Document, overlay: Document | null): Answer {
  const ids = [base.doc_id, ...(overlay ? [overlay.doc_id] : [])]
  return { answer_id: `overlay-${crypto.randomUUID()}`, question, doc_ids: ids,
    answer: { text_md: overlay ? '**Opening the sheet overlay.** Check the alignment in the drawing viewer. [1] [2]' : '**Choose a second sheet to overlay.** The drawing viewer will check the alignment. [1]', value: null, unit: null, confidence: 0, abstained: false },
    citations: ids.map((doc_id, i) => ({ n: i+1, doc_id, page: 1, kind: 'region', bbox_px: null, item_ids: [], quote: null })),
    evidence: { boxes: [], scene: { doc_id: base.doc_id, highlight_item_ids: [], camera_target_item_id: null } },
    reasoning: { steps: [{ kind: 'found', title: 'Source sheets', text: 'Opened the source sheets for comparison. Registration is checked separately in the viewer.', cite: 1 }], confidence: { label: 'Estimate', pct: null, reason: 'Alignment has not yet been checked. No measured accuracy is available for this answer type.' } },
    trace: [], route: 'index', cost: { usd_total: 0, calls: [] }, latency_ms: 0 }
}

/** Report the actual fit and cite both originals. Anchor consensus is not calibrated accuracy. */
export function overlayAlignedAnswer(previous: Answer, result: Alignment, base: Document, overlay: Document, basePage = 1, overlayPage = 1): Answer {
  const accepted = result.anchor_count, candidates = result.candidate_count
  const manual = result.status === 'manual', aligned = result.status === 'aligned'
  const boxes = aligned ? result.anchors.filter((a) => a.base_bbox).slice(0, 12).map((a, i) => ({ item_id: `alignment-anchor-${i+1}`, page: basePage, bbox_px: a.base_bbox!, label: String(i+1) })) : []
  return { ...previous, doc_ids: [base.doc_id, overlay.doc_id],
    answer: { ...previous.answer, text_md: `**${result.detail}** [1] [2]`, confidence: 0 },
    citations: [base, overlay].map((doc, i) => ({ n: i+1, doc_id: doc.doc_id, page: i ? overlayPage : basePage, kind: 'region', bbox_px: null, item_ids: i ? [] : boxes.map((b) => b.item_id), quote: null })),
    evidence: { ...previous.evidence, boxes },
    reasoning: { steps: [{ kind: 'checked', title: manual ? 'Manual registration' : aligned ? 'Shared drawing anchors' : 'Alignment needs input', text: result.detail, cite: 1, ok: aligned ? true : null }],
      confidence: { label: aligned ? 'Cross-checked' : 'Estimate', pct: null,
        reason: aligned ? `${accepted} of ${candidates} candidate anchors agree with the fit. This is registration support, not measurement accuracy. No measured accuracy is available for this answer type.` : 'Automatic accuracy is unavailable. Check a third grid crossing before relying on the overlay.' } } }
}

export async function requestAlignment(base: string, overlay: string, basePage: number, overlayPage: number, signal: AbortSignal, points?: { base: XY[]; overlay: XY[] }): Promise<Alignment> {
  const response = await fetch('/api/sheet-align', { method: 'POST', headers: { 'Content-Type': 'application/json' }, signal,
    body: JSON.stringify({ base_doc_id: base, overlay_doc_id: overlay, base_page: basePage, overlay_page: overlayPage,
      ...(points ? { base_points: points.base, overlay_points: points.overlay } : {}) }) })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(typeof body.detail === 'string' ? body.detail : 'These sheets could not be aligned. Try choosing two points.')
  }
  const result = await response.json() as Alignment
  if (result.pair_key) {
    // Content key includes page images and positioned text, so updated sources invalidate a manual fit.
    const key = `sheet-alignment:${base}:${basePage}:${overlay}:${overlayPage}:${result.pair_key}`
    try {
      if (points) sessionStorage.setItem(key, JSON.stringify(result))
      else {
        const saved = sessionStorage.getItem(key)
        if (saved) {
          const manual = JSON.parse(saved) as Alignment
          if (manual.pair_key === result.pair_key && manual.status === 'manual' && manual.matrix) return manual
        }
      }
    } catch { /* Storage may be disabled; registration still works for the current view. */ }
  }
  return result
}

export const cssMatrix = (m: Matrix) => `matrix(${m[0][0]},${m[1][0]},${m[0][1]},${m[1][1]},${m[0][2]},${m[1][2]})`

/** Pre-register into base page coordinates so the shared SheetCompare needs no special transform logic. */
export async function registeredSheet(src: string, matrix: Matrix, size: SheetSize): Promise<string> {
  const image = await new Promise<HTMLImageElement>((resolve, reject) => {
    const image = new Image(); image.onload = () => resolve(image); image.onerror = () => reject(new Error('The overlay page image could not be loaded.')); image.src = src
  })
  const canvas = document.createElement('canvas'), k = Math.min(1, 3500 / Math.max(size.w, size.h))
  canvas.width = Math.round(size.w*k); canvas.height = Math.round(size.h*k)
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('This browser cannot draw the registered sheet.')
  ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, canvas.width, canvas.height); ctx.scale(k, k)
  const [[a,c,e],[b,d,f]] = matrix; ctx.transform(a,b,c,d,e,f); ctx.drawImage(image, 0, 0)
  const blob = await new Promise<Blob>((resolve, reject) => canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error('The registered image could not be created.')), 'image/png'))
  return URL.createObjectURL(blob)
}
