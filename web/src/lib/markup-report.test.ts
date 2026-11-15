import { expect, it } from 'vitest'
import { notesHtml, notesMarkdown } from './markup-report'
const notes = [{ docId: 'any', title: 'Electrical <sheet>', pins: [{ id: 'pin', doc_id: 'any', n: 3, page: 2, x: 120, y: 40, note: '<script>alert(1)</script> check & confirm' }] }]
it('exports pins with their actual page, position and number, safely escaped', () => {
  const html = notesHtml(notes), md = notesMarkdown(notes)
  expect(html).toContain('Pin 3 · Page 2')
  expect(html).toContain('[120, 40] page pixels')
  expect(html).not.toContain('<script>')
  expect(md).toContain('Pin 3 · Page 2')
  expect(md).toContain('&lt;script&gt;')
})
it('reports unavailable site notes rather than silently excluding them', () => {
  const n = [{ docId: 'sheet', title: 'Sheet', pins: [], notice: 'Site notes unavailable' }]
  expect(notesHtml(n)).toContain('Site notes unavailable')
  expect(notesMarkdown(n)).toContain('Site notes unavailable')
  expect(notesHtml([])).toBe('')
})
