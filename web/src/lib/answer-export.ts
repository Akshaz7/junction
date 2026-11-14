import type { Answer, Bbox, Document, SavedChat } from './types'
import { savedExchanges } from './chat-history'
import { kindFromItemId, kindStyle } from './kind-colors'
import { confidenceText, marginText } from './evidence-format'

export interface ReportSource {
  docId: string
  title: string
  licence: string
  credit: string
}
export interface ReportRegion { label: string; bbox: Bbox; itemId?: string }
export interface ReportPage {
  key: string
  source: ReportSource
  page: number
  imageUrl: string
  regions: ReportRegion[]
}
export interface ReportEntry {
  question: string
  textMd: string
  costUsd: number | null
  generatedForDemo: boolean
  citations: (Answer['citations'][number] & { source: ReportSource })[]
  sources: ReportSource[]
  pages: ReportPage[]
  reasoning?: Answer['reasoning']
}
export interface AnswerReport {
  title: string
  generatedAt: string
  chatId?: string
  entries: ReportEntry[]
}
export interface ReportOptions { generatedAt?: Date; chatId?: string; baseUrl?: string; demo?: boolean }
export interface ReportDrawing { dataUrl?: string; notice?: string }

function sourceFor(docId: string, docs: readonly Document[]): ReportSource {
  const doc = docs.find((item) => item.doc_id === docId)
  return { docId, title: doc?.title || docId, licence: doc?.licence || 'Licence not supplied', credit: doc?.credit || 'Credit not supplied' }
}

export function reportPageUrl(docId: string, page: number, baseUrl?: string): string {
  const path = `/api/docs/${encodeURIComponent(docId)}/pages/${page}/image`
  return baseUrl ? new URL(path, baseUrl).href : path
}

function entryFor(answer: Answer, docs: readonly Document[], index: number, options: ReportOptions): ReportEntry {
  const sources = [...new Set([...answer.doc_ids, ...answer.citations.map((citation) => citation.doc_id), answer.evidence.scene.doc_id].filter(Boolean))]
    .map((id) => sourceFor(id, docs))
  const citations = answer.citations.map((citation) => ({ ...citation, source: sourceFor(citation.doc_id, docs) }))
  const pages: ReportPage[] = []
  function pageFor(docId: string, page: number) {
    if (!docId || !Number.isInteger(page) || page < 1) return undefined
    let result = pages.find((entry) => entry.source.docId === docId && entry.page === page)
    if (!result) {
      result = { key: JSON.stringify([index, docId, page]), source: sourceFor(docId, docs), page, imageUrl: reportPageUrl(docId, page, options.baseUrl), regions: [] }
      pages.push(result)
    }
    return result
  }
  for (const citation of citations) pageFor(citation.doc_id, citation.page)
  const boxDoc = answer.evidence.scene.doc_id || (answer.doc_ids.length === 1 ? answer.doc_ids[0] : '')
  for (const box of answer.evidence.boxes) {
    // Boxes lack doc_id. Never put an ambiguous or another document's box on a page.
    const owners = [...new Set(citations.filter((citation) => citation.page === box.page && citation.item_ids.includes(box.item_id)).map((citation) => citation.doc_id))]
    const docId = boxDoc || (owners.length === 1 ? owners[0] : '')
    pageFor(docId, box.page)?.regions.push({ label: box.label, bbox: [...box.bbox_px], itemId: box.item_id })
  }
  for (const citation of citations) {
    const page = pageFor(citation.doc_id, citation.page)
    if (page && citation.bbox_px && (citation.kind === 'text' || !citation.item_ids.some((id) => page.regions.some((region) => region.itemId === id)))) {
      page.regions.push({ label: String(citation.n), bbox: [...citation.bbox_px] })
    }
  }
  return {
    question: answer.question, textMd: answer.answer.text_md,
    costUsd: Number.isFinite(answer.cost.usd_total) && answer.cost.usd_total >= 0 ? answer.cost.usd_total : null,
    generatedForDemo: !!options.demo || answer.trace.some((step) => step.stub) || sources.some((source) => /generated for demo/i.test(`${source.title} ${source.credit}`)),
    citations, sources, pages, reasoning: answer.reasoning ? structuredClone(answer.reasoning) : undefined,
  }
}

export function buildAnswerReport(answers: Answer | readonly Answer[], docs: readonly Document[], options: ReportOptions = {}): AnswerReport {
  const list = Array.isArray(answers) ? answers : [answers as Answer]
  return {
    title: 'Site report', generatedAt: (options.generatedAt ?? new Date()).toISOString(), chatId: options.chatId,
    entries: list.map((answer, index) => entryFor(answer, docs, index, options)),
  }
}

export function buildChatReport(chat: SavedChat, docs: readonly Document[], options: ReportOptions = {}): AnswerReport {
  const report = buildAnswerReport([], docs, { ...options, chatId: chat.id })
  report.title = 'Chat site report'
  report.entries = savedExchanges(chat).map((exchange, index) => exchange.answer
    ? { ...entryFor(exchange.answer, docs, index, options), question: exchange.question || exchange.answer.question }
    : { question: exchange.question, textMd: exchange.content || 'No answer recorded.', costUsd: null, generatedForDemo: !!options.demo, citations: [], sources: [], pages: [] })
  return report
}

/** Keep source coordinates until rendering, clamping malformed/out-of-page boxes. */
export function reportCrop(regions: readonly ReportRegion[], width: number, height: number): { crop: Bbox; regions: ReportRegion[] } {
  const valid = regions.flatMap((region) => {
    if (!region.bbox.every(Number.isFinite)) return []
    const [x0, y0, x1, y1] = region.bbox
    const bbox: Bbox = [Math.max(0, x0), Math.max(0, y0), Math.min(width, x1), Math.min(height, y1)]
    return bbox[2] > bbox[0] && bbox[3] > bbox[1] ? [{ ...region, bbox }] : []
  })
  if (!valid.length) return { crop: [0, 0, width, height], regions: [] }
  const bounds: Bbox = [width, height, 0, 0]
  for (const { bbox } of valid) {
    bounds[0] = Math.min(bounds[0], bbox[0]); bounds[1] = Math.min(bounds[1], bbox[1])
    bounds[2] = Math.max(bounds[2], bbox[2]); bounds[3] = Math.max(bounds[3], bbox[3])
  }
  const pad = Math.max(40, Math.max(bounds[2] - bounds[0], bounds[3] - bounds[1]) * 0.05)
  return { crop: [Math.max(0, Math.floor(bounds[0] - pad)), Math.max(0, Math.floor(bounds[1] - pad)), Math.min(width, Math.ceil(bounds[2] + pad)), Math.min(height, Math.ceil(bounds[3] + pad))], regions: valid }
}

/** Canvas is bounded for phone memory. Labels match the supplied evidence, never renumbered. */
export function drawReportPage(image: CanvasImageSource, width: number, height: number, regions: readonly ReportRegion[], canvas: HTMLCanvasElement): string {
  if (!(width > 0 && height > 0)) throw new Error('The drawing has no image dimensions.')
  const { crop, regions: visible } = reportCrop(regions, width, height)
  const [x, y, right, bottom] = crop
  const scale = Math.min(1, 2000 / Math.max(right - x, bottom - y))
  canvas.width = Math.max(1, Math.ceil((right - x) * scale))
  canvas.height = Math.max(1, Math.ceil((bottom - y) * scale))
  const context = canvas.getContext('2d')
  if (!context) throw new Error('Drawing export is unavailable in this browser.')
  context.fillStyle = '#ffffff'
  context.fillRect(0, 0, canvas.width, canvas.height)
  context.drawImage(image, x, y, right - x, bottom - y, 0, 0, canvas.width, canvas.height)
  const sx = canvas.width / (right - x), sy = canvas.height / (bottom - y)
  for (const region of visible) {
    const [x0, y0, x1, y1] = region.bbox
    const left = (x0 - x) * sx, top = (y0 - y) * sy
    const style = kindStyle(region.itemId ? kindFromItemId(region.itemId) : null)
    context.strokeStyle = style.color
    context.lineWidth = 2
    context.strokeRect(left, top, (x1 - x0) * sx, (y1 - y0) * sy)
  }
  // Draw labels last so other boxes never paint over them.
  for (const region of visible) {
    const style = kindStyle(region.itemId ? kindFromItemId(region.itemId) : null)
    context.font = 'bold 14px sans-serif'
    const labelWidth = Math.min(canvas.width, context.measureText(region.label).width + 12)
    const left = Math.max(0, Math.min((region.bbox[0] - x) * sx, canvas.width - labelWidth))
    const top = Math.max(0, Math.min((region.bbox[1] - y) * sy - 23, canvas.height - 22))
    context.fillStyle = style.color
    context.fillRect(left, top, labelWidth, 22)
    context.fillStyle = style.on
    context.fillText(region.label, left + 6, top + 16)
  }
  return canvas.toDataURL('image/png')
}

const mdEscape = (text: string) => text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/([\\`*_[\]{}()#+.!|>~-])/g, '\\$1')
const money = (cost: number | null) => cost === null ? 'Not recorded' : `$${cost} USD`

/** Include the complete card and every arithmetic term in both export formats. */
function evidenceLines(reasoning: Answer['reasoning']): string[] {
  if (!reasoning) return []
  const lines = reasoning.steps.map((step) => `${step.title}: ${step.text}${step.cite != null ? ` [${step.cite}]` : ''}${step.ok === true ? ' (matches)' : step.ok === false ? ' (differs)' : ''}`)
  if (reasoning.based_on) lines.push(reasoning.based_on.text)
  if (reasoning.margin) {
    lines.push(marginText(reasoning.margin))
    for (const [kind, margin] of Object.entries(reasoning.margin.by_kind ?? {})) {
      lines.push(`${kind}: ${marginText(margin)}`)
      if (margin.sources.length) lines.push(`Margin sources (${kind}): ${margin.sources.join('; ')}`)
    }
    if (reasoning.margin.sources.length) lines.push(`Margin sources: ${reasoning.margin.sources.join('; ')}`)
  }
  lines.push(confidenceText(reasoning.confidence), reasoning.confidence.reason)
  if (reasoning.confidence.improve) lines.push(`To verify: ${reasoning.confidence.improve}`)
  const calibration = reasoning.confidence.calibration
  if (calibration) lines.push(`Calibration: ${calibration.correct}/${calibration.n} · ${calibration.source}${calibration.scope ? ` — ${calibration.scope}` : ''}`)
  if (calibration?.interval_95) lines.push(`Audit 95% interval: ${calibration.interval_95.map((value) => `${(value * 100).toFixed(1)}%`).join('–')}`)
  for (const calculation of reasoning.arithmetic ?? []) {
    lines.push(`${calculation.formula}: result ${calculation.result} ${calculation.unit}`)
    for (const term of calculation.terms) {
      lines.push(`${term.value} ${term.unit}${term.cite != null ? ` [${term.cite}]` : ''} · ${term.doc_id} · ${term.item_id}`)
      if (term.measurement) lines.push(`${term.measurement.formula}: ${term.measurement.operands.map((operand) => `${operand.value} ${operand.unit}`).join(' × ')} = ${term.value} ${term.unit}`)
    }
  }
  return lines
}

export function reportToMarkdown(report: AnswerReport): string {
  const lines = [`# ${report.title}`, '', `Generated: ${report.generatedAt}`, ...(report.chatId ? [`Chat: ${mdEscape(report.chatId)}`] : [])]
  for (const entry of report.entries) {
    lines.push('', '## Question', '', mdEscape(entry.question), '', '## Answer', '', entry.textMd.replace(/</g, '&lt;').replace(/>/g, '&gt;'))
    if (entry.generatedForDemo) lines.push('', '_generated for demo_')
    const evidence = evidenceLines(entry.reasoning)
    if (evidence.length) lines.push('', '### How we know', '', ...evidence.map((line) => `- ${mdEscape(line)}`))
    lines.push('', `Answer cost: ${money(entry.costUsd)}`, '', '### Where it is set out', '')
    if (!entry.citations.length) lines.push('No numbered citations supplied.')
    for (const citation of entry.citations) {
      lines.push(`- [${citation.n}] ${mdEscape(citation.source.title)} · Page ${citation.page}${citation.quote ? ` — ${mdEscape(citation.quote)}` : ''}`)
      if (citation.item_ids.length) lines.push(`  Items: ${citation.item_ids.map(mdEscape).join(', ')}`)
    }
    for (const source of entry.sources) lines.push('', `Source: ${mdEscape(source.title)}`, '', `Licence: ${mdEscape(source.licence)} · Credit: ${mdEscape(source.credit)}`)
    for (const page of entry.pages) {
      lines.push('', `[${mdEscape(page.source.title)} · Page ${page.page} — original drawing, without report overlays](<${page.imageUrl}>)`)
      for (const region of page.regions) lines.push(`- Box ${mdEscape(region.label)}${region.itemId ? ` · ${mdEscape(region.itemId)}` : ''}: [${region.bbox.join(', ')}] page pixels`)
    }
  }
  lines.push('', 'AI can make mistakes. Verify important information.', '')
  return lines.join('\n')
}

const htmlEscape = (value: string) => value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;')
// Match the app's supported answer formatting; raw HTML is always plain text.
const answerHtml = (text: string) => htmlEscape(text).replace(/\*\*([\s\S]+?)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>')

/** A standalone document: inline images and styles remain printable without the app shell. */
export function reportToHtml(report: AnswerReport, drawings: Readonly<Record<string, ReportDrawing>>, stylesheet: string): string {
  const entries = report.entries.map((entry) => `<section class="site-report-entry">
    <h2>Question</h2><p>${htmlEscape(entry.question)}</p><h2>Answer</h2><p>${answerHtml(entry.textMd)}</p>
    ${entry.generatedForDemo ? '<p class="site-report-note">generated for demo</p>' : ''}
    <p class="site-report-note">Answer cost: ${money(entry.costUsd)}</p>
    ${entry.reasoning ? `<h3>How we know</h3><ul>${evidenceLines(entry.reasoning).map((line) => `<li>${htmlEscape(line)}</li>`).join('')}</ul>` : ''}
    <h3>Where it is set out</h3>${entry.citations.length ? `<ul>${entry.citations.map((citation) => `<li><strong>[${citation.n}] ${htmlEscape(citation.source.title)} · Page ${citation.page}</strong>${citation.quote ? `<p>${htmlEscape(citation.quote)}</p>` : ''}${citation.item_ids.length ? `<p class="site-report-note">Items: ${htmlEscape(citation.item_ids.join(', '))}</p>` : ''}</li>`).join('')}</ul>` : '<p>No numbered citations supplied.</p>'}
    ${entry.sources.map((source) => `<p class="site-report-credit"><strong>${htmlEscape(source.title)}</strong><br>Licence: ${htmlEscape(source.licence)} · Credit: ${htmlEscape(source.credit)}</p>`).join('')}
    ${entry.pages.map((page) => {
      const drawing = drawings[page.key]
      const dataUrl = drawing?.dataUrl?.startsWith('data:image/png;base64,') ? drawing.dataUrl : undefined
      return `<figure>${dataUrl ? `<img src="${htmlEscape(dataUrl)}" alt="${htmlEscape(page.source.title)} · Page ${page.page}, drawing evidence">` : ''}<figcaption><strong>${htmlEscape(page.source.title)} · Page ${page.page}</strong>${drawing?.notice ? `<br>${htmlEscape(drawing.notice)}` : !dataUrl ? '<br>Drawing unavailable; no image evidence included.' : ''}<br>Licence: ${htmlEscape(page.source.licence)} · Credit: ${htmlEscape(page.source.credit)}</figcaption></figure>`
    }).join('')}
  </section>`).join('')
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>${htmlEscape(report.title)}</title><style>${stylesheet.replace(/<\/style/gi, '<\\/style')}</style></head><body class="site-report"><header><p>Hologram</p><h1>${htmlEscape(report.title)}</h1><p class="site-report-note">Generated: ${htmlEscape(report.generatedAt)}${report.chatId ? `<br>Chat: ${htmlEscape(report.chatId)}` : ''}</p></header><main>${entries || '<p>No recorded answers.</p>'}</main><footer>AI can make mistakes. Verify important information.</footer></body></html>`
}
