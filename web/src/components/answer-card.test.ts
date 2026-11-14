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
    expect(html).toContain('Where it is set out')
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
})
