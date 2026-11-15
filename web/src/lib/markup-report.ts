import { markupRequest, type MarkupPin } from '../components/viewer-tools/markup-api'
export interface ReportNotes { docId: string; title: string; pins: MarkupPin[]; notice?: string }
const escapeHtml = (s: string) => s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!)
const escapeMd = (s: string) => s.replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/([\\`*_[\]{}()#+.!|>~-])/g, '\\$1')
export async function loadReportNotes(docs: { docId: string; title: string }[], signal: AbortSignal): Promise<ReportNotes[]> {
  return Promise.all(docs.map(async (doc) => {
    try { return { ...doc, pins: await markupRequest<MarkupPin[]>(doc.docId, '/pins', { signal }) } }
    catch { signal.throwIfAborted(); return { ...doc, pins: [], notice: 'Saved note pins could not be loaded; this report may omit site notes.' } }
  }))
}
export function notesMarkdown(notes: ReportNotes[] = []): string {
  const visible = notes.filter((d) => d.pins.length || d.notice)
  if (!visible.length) return ''
  return '\n\n## Site note pins\n\n' + visible.map((d) => `### ${escapeMd(d.title)}\n\n` + (d.notice ? escapeMd(d.notice) + '\n' : '') + d.pins.map((p) => `- Pin ${p.n} · Page ${p.page} · [${p.x}, ${p.y}] page pixels: ${escapeMd(p.note)}`).join('\n')).join('\n\n')
}
export function notesHtml(notes: ReportNotes[] = []): string {
  const visible = notes.filter((d) => d.pins.length || d.notice)
  if (!visible.length) return ''
  return '<section class="site-report-entry"><h2>Site note pins</h2>' + visible.map((d) => `<h3>${escapeHtml(d.title)}</h3>${d.notice ? `<p>${escapeHtml(d.notice)}</p>` : ''}<ol>${d.pins.map((p) => `<li><strong>Pin ${p.n} · Page ${p.page}</strong> · [${p.x}, ${p.y}] page pixels<p>${escapeHtml(p.note)}</p></li>`).join('')}</ol>`).join('') + '</section>'
}
