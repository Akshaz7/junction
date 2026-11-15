import { expect, it } from 'vitest'
import { makeDemoAnswer } from '../mock/handler'
import { buildAnswerReport, reportToHtml, reportToMarkdown } from './answer-export'
import type { Calculation } from './types'

it('includes every calculation row, formula, sourced input, check and margin in both existing report formats', () => {
  const answer = makeDemoAnswer('How many windows?')
  const calc: Calculation = {
    formula: 'area = width × height', status: 'complete',
    steps: [{ id: 's1', label: 'Opening area', expr: '2 × 3', value: 6, unit: 'm2', inputs: [
      { name: 'width', value: 2, unit: 'm', source: { doc_id: 'source', page: 2, item_id: 'door-1', artifact: 'elements.json', field: 'width_m' } },
    ] }],
    rows: Array.from({ length: 301 }, (_, i) => ({ item_id: `row-${i}`, label: i === 300 ? '<script>last</script>' : 'Opening', values: { area_m2: 6 }, source: { kind: 'step', step_id: 's1' } })),
    result: { value: 6, unit: 'm2', rounded_as: '1 decimal place', additional: [{ label: 'Converted', value: 64.6, unit: 'ft2' }] },
    checks: [{ method: 'Printed label', value: 6, agrees: true, diff_pct: 0 }],
    margin: { value: .05, unit: 'm2', pct: null, why: 'Display rounding only', sources: ['source'] },
  }
  answer.reasoning = { steps: [], confidence: { label: 'Estimate', pct: null, reason: 'No independent check' }, calc }
  const report = buildAnswerReport(answer, [])
  const md = reportToMarkdown(report), html = reportToHtml(report, {}, '')
  expect(md).toContain('Calculation report')
  expect(md).toContain('width')
  expect(md).toContain('elements\\.json')
  expect(html).toContain('row-300')
  expect(html).toContain('&lt;script&gt;last&lt;/script&gt;')
  expect(html).not.toContain('<script>')
  expect(html).toContain('Printed label')
  expect(html).toContain('Display rounding only')
  expect(html).toContain('Converted: 64.6 ft2')
})
