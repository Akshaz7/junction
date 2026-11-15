import { describe, expect, it, vi } from 'vitest'
import { demoDocument, makeDemoAnswer } from '../mock/handler'
import type { Bbox, SavedChat } from './types'
import { buildAnswerReport, buildChatReport, drawReportPage, reportCrop, reportPageUrl, reportToHtml, reportToMarkdown } from './answer-export'

const options = { generatedAt: new Date('2026-11-14T12:00:00.000Z'), chatId: 'chat/1', baseUrl: 'https://hologram.example' }
const answer = () => makeDemoAnswer('How many windows are there?')

it('exports the complete evidence card and every term beyond the preview', () => {
  const input = answer()
  input.reasoning = {
    steps: [{ kind: 'calculated', title: 'Calculated', text: '1 + 2 + 3 + 4 + 5 + 6 + 1 more = 28 m²' }],
    confidence: { label: 'Verified', pct: null, reason: 'Source quantities reproduce the answer.', calibration: { n: 2, correct: 1, source: 'calibration.json' } },
    margin: { value: .05, unit: 'm2', pct: .18, why: 'Rounding only <check>.', sources: ['source quantities'] },
    based_on: { elements: 7, estimated: 0, unresolved: 0, text: 'Based on 7 elements; 0 estimated.' },
    arithmetic: [{ formula: 'Add source areas', text: 'preview', result: 28, unit: 'm2', terms: Array.from({ length: 7 }, (_, i) => ({ doc_id: 'd', item_id: `term-${i}`, cite: 1, value: i + 1, unit: 'm2' })) }],
  }
  const report = buildAnswerReport(input, [], options)
  const markdown = reportToMarkdown(report), html = reportToHtml(report, {}, '')
  expect(markdown).toContain('### How we know')
  expect(markdown).toContain('Based on 7 elements; 0 estimated')
  expect(markdown).toContain('term\\-6')
  expect(html).toContain('term-6')
  expect(html).toContain('± 0.05 m² (± 0.18%)')
  expect(html).toContain('&lt;check&gt;')
  expect(html).not.toContain('<check>')
  expect(html).not.toContain('null%')
  expect(html).toContain('Calibration: 1/2')
  report.entries[0].reasoning!.arithmetic![0].terms[0].value = 500
  expect(input.reasoning.arithmetic![0].terms[0].value).toBe(1)
})

describe('answer export report model', () => {
  it('preserves proof labels, citations, attribution, cost, and a deterministic generated date', () => {
    const input = answer()
    input.cost.usd_total = 0.000013
    input.evidence.boxes[0].label = '7'
    const report = buildAnswerReport(input, [demoDocument], options)
    expect(report.generatedAt).toBe(options.generatedAt.toISOString())
    expect(report.chatId).toBe('chat/1')
    const entry = report.entries[0]
    expect(entry.question).toBe(input.question)
    expect(entry.textMd).toBe(input.answer.text_md)
    expect(entry.costUsd).toBe(0.000013)
    expect(entry.generatedForDemo).toBe(true)
    expect(entry.citations[0]).toMatchObject({ n: 1, source: { title: demoDocument.title, licence: 'MIT', credit: demoDocument.credit } })
    expect(entry.pages).toHaveLength(1)
    expect(entry.pages[0].regions.map((region) => region.label)).toEqual(['7', '2'])
    expect(entry.pages[0].imageUrl).toBe('https://hologram.example/api/docs/demo__garden-room/pages/1/image')
    entry.pages[0].regions[0].bbox[0] = 5
    expect(input.evidence.boxes[0].bbox_px[0]).toBe(100)
  })

  it('keeps evidence on its own document and page even when IDs repeat across documents', () => {
    const input = answer()
    input.doc_ids.push('second-doc')
    input.citations.push({ ...input.citations[0], n: 2, doc_id: 'second-doc' })
    input.evidence.boxes.push({ ...input.evidence.boxes[0], page: 2, label: '9' })
    const pages = buildAnswerReport(input, [demoDocument], options).entries[0].pages
    expect(pages.find((page) => page.source.docId === 'second-doc')?.regions).toEqual([])
    expect(pages.find((page) => page.source.docId === demoDocument.doc_id && page.page === 1)?.regions).toHaveLength(2)
    expect(pages.find((page) => page.page === 2)?.regions[0].label).toBe('9')
  })

  it('uses unique citation ownership when boxes have no scene doc and omits ambiguous boxes', () => {
    const input = answer()
    input.evidence.scene.doc_id = ''
    input.doc_ids.push('other')
    expect(buildAnswerReport(input, [], options).entries[0].pages[0].regions).toHaveLength(2)
    input.citations.push({ ...input.citations[0], n: 2, doc_id: 'other' })
    expect(buildAnswerReport(input, [], options).entries[0].pages.every((page) => page.regions.length === 0)).toBe(true)
  })

  it('includes text citation regions and gives honest missing metadata and cost values', () => {
    const input = answer()
    input.cost.usd_total = Number.NaN
    input.citations.push({ ...input.citations[0], n: 3, kind: 'text', page: 2, bbox_px: [12, 34, 56, 78], quote: 'Window schedule', item_ids: [] })
    const entry = buildAnswerReport(input, [], options).entries[0]
    expect(entry.costUsd).toBeNull()
    expect(entry.sources[0]).toMatchObject({ title: demoDocument.doc_id, licence: 'Licence not supplied', credit: 'Credit not supplied' })
    expect(entry.pages.find((page) => page.page === 2)?.regions).toEqual([{ label: '3', bbox: [12, 34, 56, 78] }])
  })

  it('exports abstentions and zero costs without inventing citations or drawings', () => {
    const report = buildAnswerReport(makeDemoAnswer('Is this safe?'), [], options)
    expect(report.entries[0]).toMatchObject({ costUsd: 0, citations: [], pages: [] })
    expect(report.entries[0].textMd).toContain('do not hold an answer')
    const markdown = reportToMarkdown(report)
    expect(markdown).toContain('Answer cost: $0 USD')
    expect(markdown).toContain('No numbered citations supplied.')
  })

  it('preserves full chat order including plain replies, unanswered questions, and per-answer cost', () => {
    const chat: SavedChat = { id: 'saved-chat', doc_id: demoDocument.doc_id, messages: [
      { id: '1', role: 'user', content: 'Original question', answer: null },
      { id: '2', role: 'assistant', content: '', answer: answer() },
      { id: '3', role: 'user', content: 'Follow-up', answer: null },
      { id: '4', role: 'assistant', content: 'No drawing supplied.', answer: null },
      { id: '5', role: 'user', content: 'Still waiting', answer: null },
    ] }
    const report = buildChatReport(chat, [demoDocument], options)
    expect(report.title).toBe('Chat site report')
    expect(report.chatId).toBe('saved-chat')
    expect(report.entries.map((entry) => entry.question)).toEqual(['Original question', 'Follow-up', 'Still waiting'])
    expect(report.entries.map((entry) => entry.costUsd)).toEqual([0, null, null])
    expect(report.entries[1].textMd).toBe('No drawing supplied.')
    expect(report.entries[2].textMd).toBe('No answer recorded.')
  })

  it('encodes document IDs as one path segment', () => {
    expect(reportPageUrl('drawing/a?#', 2)).toBe('/api/docs/drawing%2Fa%3F%23/pages/2/image')
  })
})

describe('report Markdown and standalone HTML', () => {
  it('includes numbered sources, quotes, metadata, original image links, coordinates, and demo labels', () => {
    const input = answer()
    input.citations[0].quote = 'Window type A'
    input.cost.usd_total = 0.000013
    const markdown = reportToMarkdown(buildAnswerReport(input, [demoDocument], options))
    expect(markdown).toContain('Generated: 2026-11-14T12:00:00.000Z')
    expect(markdown).toContain('## Question\n\nHow many windows are there?')
    expect(markdown).toContain('**2 windows**')
    expect(markdown).toContain('- [1] Garden room — generated for demo · Page 1 — Window type A')
    expect(markdown).toContain('Licence: MIT · Credit: Hologram team · generated for demo')
    expect(markdown).toContain('Answer cost: $0.000013 USD')
    expect(markdown).toContain('_generated for demo_')
    expect(markdown).toContain('original drawing, without report overlays](<https://hologram.example/api/docs/demo__garden-room/pages/1/image>)')
    expect(markdown).toContain('Box 2 · window\\-002: [260, 40, 340, 52] page pixels')
  })

  it('keeps repeated citation numbering local to each answer in a multi-answer report', () => {
    const report = buildAnswerReport([answer(), answer()], [demoDocument], options)
    expect(report.entries[0].pages[0].key).not.toBe(report.entries[1].pages[0].key)
    expect(reportToMarkdown(report).match(/- \[1\]/g)).toHaveLength(2)
  })

  it('escapes source metadata and raw HTML without losing supported answer bold text', () => {
    const input = answer()
    input.question = '<img src=x onerror=alert(1)>'
    input.answer.text_md = '**Recorded fact** <script>alert(1)</script> [1]'
    input.citations[0].quote = '<script>quote</script>'
    const report = buildAnswerReport(input, [{ ...demoDocument, title: 'Floor [fake](javascript:bad)', credit: '<iframe>' }], options)
    const markdown = reportToMarkdown(report)
    expect(markdown).toContain('&lt;script&gt;alert(1)&lt;/script&gt;')
    expect(markdown).toContain('Floor \\[fake\\]\\(javascript:bad\\)')
    const html = reportToHtml(report, {}, '@media print { body { color: black } }')
    expect(html).not.toContain('<script>')
    expect(html).not.toContain('<img src=x')
    expect(html).toContain('<strong>Recorded fact</strong>')
    expect(html).toContain('&lt;iframe&gt;')
    expect(html).toContain('@media print')
    expect(html).toContain('Drawing unavailable; no image evidence included.')
  })

  it('embeds only generated PNG images, with attribution and unavailable-image notices', () => {
    const report = buildAnswerReport(answer(), [demoDocument], options)
    const key = report.entries[0].pages[0].key
    const html = reportToHtml(report, { [key]: { dataUrl: 'data:image/png;base64,abc', notice: 'Some boxes unavailable.' } }, '')
    expect(html).toContain('src="data:image/png;base64,abc"')
    expect(html).toContain('Some boxes unavailable.')
    expect(html).toContain('Licence: MIT · Credit: Hologram team')
    expect(reportToHtml(report, { [key]: { dataUrl: 'javascript:alert(1)' } }, '')).not.toContain('src="javascript:')
  })
})

describe('report drawing crop and canvas', () => {
  it('crops to the union of valid boxes with context and clamps page edges', () => {
    const result = reportCrop([
      { label: '1', bbox: [100, 100, 150, 120] }, { label: '2', bbox: [260, 100, 340, 120] },
      { label: 'bad', bbox: [2000, 0, 3000, 30] }, { label: 'NaN', bbox: [NaN, 0, 3, 5] },
    ], 500, 300)
    expect(result.crop).toEqual([60, 60, 380, 160])
    expect(result.regions.map((region) => region.label)).toEqual(['1', '2'])
    expect(reportCrop([{ label: 'edge', bbox: [-10, -20, 20, 30] }], 500, 300).crop).toEqual([0, 0, 60, 70])
    expect(reportCrop([], 500, 300).crop).toEqual([0, 0, 500, 300])
  })

  it('draws the correct crop and supplied labels on a bounded canvas', () => {
    const context = { fillRect: vi.fn(), drawImage: vi.fn(), strokeRect: vi.fn(), fillText: vi.fn(), measureText: () => ({ width: 10 }) }
    const canvas = { width: 0, height: 0, getContext: () => context, toDataURL: vi.fn(() => 'data:image/png;base64,crop') } as unknown as HTMLCanvasElement
    const image = {} as CanvasImageSource
    expect(drawReportPage(image, 500, 300, [{ label: '17', itemId: 'window-001', bbox: [100, 100, 150, 120] }], canvas)).toBe('data:image/png;base64,crop')
    expect(context.drawImage).toHaveBeenCalledWith(image, 60, 60, 130, 100, 0, 0, 130, 100)
    expect(context.strokeRect).toHaveBeenCalledWith(40, 40, 50, 20)
    expect(context.fillText).toHaveBeenCalledWith('17', 46, 33)
    expect(canvas.toDataURL).toHaveBeenCalledWith('image/png')
    drawReportPage(image, 10000, 8000, [], canvas)
    expect(canvas.width).toBe(2000)
    expect(canvas.height).toBe(1600)
  })

  it('handles invalid rectangles and reports unavailable canvas support', () => {
    const boxes: Bbox[] = [[5, 5, 1, 1], [0, 0, 0, 10], [0, Infinity, 20, 30]]
    expect(reportCrop(boxes.map((bbox) => ({ label: '1', bbox })), 100, 100).regions).toEqual([])
    expect(() => drawReportPage({} as CanvasImageSource, 100, 100, [], { getContext: () => null } as unknown as HTMLCanvasElement)).toThrow('unavailable')
  })
})
