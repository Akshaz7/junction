import { describe, expect, it } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { AnswerCard, formatCost } from './answer-card'
import { demoDocument, makeDemoAnswer } from '../mock/handler'

describe('answer evidence', () => {
  it('renders bold facts, inline citation buttons, sources and cost call details', () => {
    const answer = makeDemoAnswer('How many windows are there?')
    answer.cost = { usd_total: 0.00001, calls: [{ provider: 'fake', model: 'demo', cost_usd: 0.00001 }] }
    const html = renderToStaticMarkup(createElement(AnswerCard, { answer, docs: [demoDocument], demo: true, onOpenCitation: () => {} }))
    expect(html).toContain('<strong>2 windows</strong>')
    expect(html).toContain('aria-label="Open citation 1"')
    expect(html).toContain('class="source-list"')
    expect(html).not.toContain('Where it is set out') // one-line answers drop the heading
    expect(html).toContain('aria-label="Sources 1"')
    expect(html).toContain('Show thought process')
    expect(html).toContain('data-testid="answer-cost"')
    expect(html).toContain('&lt; $0.0001')
    expect(html).toContain('&quot;provider&quot;: &quot;fake&quot;')
  })

  it('renders abstentions without citation chips or sources even when stale citations exist', () => {
    const answer = makeDemoAnswer('How many windows are there?')
    answer.answer.abstained = true
    answer.answer.text_md = 'The documents do not hold an answer. [1]'
    const html = renderToStaticMarkup(createElement(AnswerCard, { answer, docs: [demoDocument], demo: false, onOpenCitation: () => {} }))
    expect(html).toContain('The documents do not hold an answer.</p>')
    expect(html).not.toContain('Open citation')
    expect(html).not.toContain('sources-summary')
    expect(html).not.toContain('Where it is set out')
  })

  it('preserves zero cost and formats small and larger amounts', () => {
    expect(formatCost(0)).toBe('$0.0000')
    expect(formatCost(0.00001)).toBe('< $0.0001')
    expect(formatCost(0.0001)).toBe('$0.0001')
    expect(formatCost(0.12345)).toBe('$0.1235')
  })

  it('shows compact command tags, hidden badges and Undo without changing ordinary answers', () => {
    const answer = makeDemoAnswer('remove W3')
    answer.answer.abstained = false
    answer.evidence.scene.commands = [{ op: 'hide', item_ids: ['window-003'], labels: { 'window-003': 'W3' } }]
    const html = renderToStaticMarkup(createElement(AnswerCard, { answer, docs: [], demo: false, onOpenCitation: () => {}, onUndo: () => {} }))
    expect(html).toContain('W3')
    expect(html).toContain('data-hidden="true"')
    expect(html).toContain('<small>hidden</small>')
    expect(html).toContain('Undo</button>')
    answer.evidence.scene.commands = [{ op: 'highlight', item_ids: Array.from({ length: 20 }, (_, n) => `window-${n}`) }]
    const compact = renderToStaticMarkup(createElement(AnswerCard, { answer, docs: [], demo: false, onOpenCitation: () => {} }))
    expect(compact.match(/class="scene-tag"/g)).toHaveLength(12)
    expect(compact).toContain('+8 more')
    expect(compact).toContain('data-item-count="20"')
  })
})

describe('answer rendering (QA-LIVE #7)', () => {
  const render = (mutate: (answer: ReturnType<typeof makeDemoAnswer>) => void) => {
    const answer = makeDemoAnswer('How many windows are there?')
    mutate(answer)
    return renderToStaticMarkup(createElement(AnswerCard, { answer, docs: [demoDocument], demo: false, onOpenCitation: () => {} }))
  }
  it('renders markdown tables as tables and hides internal ids', () => {
    const html = render((a) => { a.answer.text_md = 'Rooms:\n\n| Room | Area |\n|---|---|\n| room-004 | **12 m²** |\n\nSee door-012 [1].' })
    expect(html).toContain('<table class="answer-table">')
    expect(html).toContain('<th scope="col">Room</th>')
    expect(html).toContain('<td>Room 4</td>')
    expect(html).toContain('<strong>12 m²</strong>')
    expect(html).toContain('Door 12')
    expect(html).not.toMatch(/room-004|door-012|\|---/)
  })
  it('strips ** from quotes and drops the section heading on one-line answers', () => {
    const html = render((a) => { a.answer.text_md = '**2 windows** [1]'; a.citations[0].quote = 'a **bold** quote' })
    expect(html).toContain('a bold quote')
    expect(html).not.toContain('**')
    expect(html).not.toContain('Where it is set out')
    expect(html).toContain('source-list')
  })
  it('caps citation chips at 8 with a +N more expander', () => {
    const html = render((a) => {
      a.answer.text_md = 'Long answer.\n\nSecond paragraph.'
      a.citations = Array.from({ length: 12 }, (_, i) => ({ ...makeDemoAnswer('How many windows are there?').citations[0], n: i + 1, quote: `Quote ${i + 1}` }))
    })
    expect(html).toContain('+4 more')
    expect(html).toContain('Quote 8')
    expect(html).not.toContain('Quote 9')
    expect(html).toContain('aria-label="Sources 12"')
  })
  it('shows document chips from answer.doc_ids', () => {
    const html = render((a) => { a.doc_ids = [demoDocument.doc_id, 'other__doc'] })
    expect(html).toContain('data-testid="answer-docs"')
    expect(html).toContain('Garden room')
    expect(html).toContain('other__doc')
  })
})

describe('scene.open (CONTRACT 3.3)', () => {
  it('shows the Show-on-table hint with a pair link when open is "ar"', () => {
    const answer = makeDemoAnswer('Show it on the table')
    answer.evidence.scene.open = 'ar'
    const html = renderToStaticMarkup(createElement(AnswerCard, { answer, docs: [demoDocument], demo: true, onOpenCitation: () => {} }))
    expect(html).toContain('data-testid="ar-hint"')
    expect(html).toContain('Open the Stoa Pro app on your iPhone and tap')
    expect(html).toContain('Pair a phone')
  })
  it('shows no hint when open is absent or "3d"', () => {
    for (const open of [undefined, '3d' as const]) {
      const answer = makeDemoAnswer('How many windows are there?')
      answer.evidence.scene.open = open
      expect(renderToStaticMarkup(createElement(AnswerCard, { answer, docs: [demoDocument], demo: true, onOpenCitation: () => {} }))).not.toContain('ar-hint')
    }
  })
})
