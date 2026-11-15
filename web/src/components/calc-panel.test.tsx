// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { CalculationPanel } from './calc-panel'
import { ErrorBoundary } from './error-boundary'
import { EvidenceCard } from './evidence-card'
import { scanReasoning } from '../lib/__fixtures__/calc-fixture'
import type { Answer } from '../lib/types'

let host: HTMLDivElement
let root: Root
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
})
afterEach(async () => { await act(async () => root.unmount()); host.remove() })

it('shows formula, ordered steps, rows with totals, checks, margin and confidence', async () => {
  await act(async () => root.render(<CalculationPanel reasoning={scanReasoning} onClose={() => {}} />))
  expect(host.querySelector('[data-testid="calc-formula"]')?.textContent).toContain(scanReasoning.calc!.formula)
  const steps = [...host.querySelectorAll('.calc-steps > li')]
  expect(steps.length).toBe(scanReasoning.calc!.steps.length)
  expect(steps[0].textContent).toContain(scanReasoning.calc!.steps[0].label)
  expect(host.querySelector('.calc-table tfoot')?.textContent).toContain('Total')
  expect(host.querySelector('[data-testid="calc-reconcile"]')).toBeTruthy()
  expect(host.querySelector('.calc-checks')).toBeTruthy()
  expect(host.querySelector('[data-section="margin"]')?.textContent).toContain('±')
  expect(host.querySelector('.calc-factors')?.textContent).toContain('pts')
  expect(host.querySelector('.calc-path')).toBeTruthy()
})

it('source links call onFocus; table sorts; close works', async () => {
  const onFocus = vi.fn(), onClose = vi.fn()
  await act(async () => root.render(<CalculationPanel reasoning={scanReasoning} onClose={onClose} onFocus={onFocus} />))
  const link = host.querySelector<HTMLButtonElement>('.calc-table .calc-source-link')
  expect(link).toBeTruthy()
  await act(async () => link!.click())
  expect(onFocus).toHaveBeenCalled()
  const th = host.querySelector<HTMLTableCellElement>('.calc-table thead th.num')!
  await act(async () => th.querySelector('button')!.click())
  expect(th.getAttribute('aria-sort')).toBe('ascending')
  await act(async () => host.querySelector<HTMLButtonElement>('[aria-label="Close calculation"]')!.click())
  expect(onClose).toHaveBeenCalled()
})

it('says so when there is no calculation', async () => {
  await act(async () => root.render(<CalculationPanel reasoning={{ ...scanReasoning, calc: undefined, graph_path: undefined }} onClose={() => {}} />))
  expect(host.textContent).toContain(scanReasoning.steps[0].text)
  await act(async () => root.render(<CalculationPanel reasoning={{ ...scanReasoning, steps: [], calc: undefined, graph_path: undefined }} onClose={() => {}} />))
  expect(host.textContent).toContain('No calculation was recorded')
})

it('evidence card shows key numbers and a Show calculation link', async () => {
  const onShow = vi.fn()
  const answer = { citations: [], reasoning: scanReasoning } as unknown as Answer
  await act(async () => root.render(<EvidenceCard answer={answer} onOpenCitation={() => {}} onShowCalculation={onShow} />))
  expect(host.querySelector('[data-testid="evidence-numbers"]')?.textContent).toContain('Scale')
  await act(async () => host.querySelector<HTMLButtonElement>('.evidence-calc-link')!.click())
  expect(onShow).toHaveBeenCalled()
})

it('expands to full width and has a resize separator', async () => {
  await act(async () => root.render(<CalculationPanel reasoning={scanReasoning} onClose={() => {}} />))
  expect(host.querySelector('[role="separator"]')).toBeTruthy()
  await act(async () => host.querySelector<HTMLButtonElement>('[aria-label="Expand calculation to full width"]')!.click())
  expect(host.querySelector('.viewer-calc-panel.is-expanded')).toBeTruthy()
  expect(host.querySelector('[role="separator"]')).toBeNull()
})

import { scanCalc, scanPrintedCalc, ifcCountCalc, ifcWallAreaCalc } from '../lib/__fixtures__/calc-fixture'
import type { Calculation } from '../lib/types'

for (const [name, calc] of [['scan door prior', scanCalc], ['scan printed scale', scanPrintedCalc], ['IFC count', ifcCountCalc], ['IFC wall area', ifcWallAreaCalc]] as [string, Calculation][]) {
  it(`renders whatever the ${name} calculation contains, with its method`, async () => {
    await act(async () => root.render(<CalculationPanel reasoning={{ ...scanReasoning, calc, graph_path: undefined }} onClose={() => {}} />))
    expect(host.querySelector('[data-testid="calc-method"]')?.textContent).toContain(calc.method!.label)
    expect(host.querySelector('[data-testid="calc-method"]')?.textContent).toContain('Why this method')
    expect(host.querySelector('.calc-alternatives')?.textContent).toContain(calc.method!.alternatives![0].rejected_because)
    expect([...host.querySelectorAll('.calc-steps > li strong')].map((n) => n.textContent)).toEqual(calc.steps.map((s) => s.label))
    expect(!!host.querySelector('.calc-table')).toBe(calc.rows.length > 0)
    expect(!!host.querySelector('.calc-checks')).toBe(calc.checks.length > 0)
  })
}

it('survives a calculation with only a formula and a result', async () => {
  const bare = { formula: 'x = 1', result: { value: 1, unit: 'count', rounded_as: 'whole' } } as unknown as Calculation
  await act(async () => root.render(<CalculationPanel reasoning={{ ...scanReasoning, calc: bare, margin: undefined, graph_path: undefined }} onClose={() => {}} />))
  expect(host.querySelector('[data-testid="calc-formula"]')).toBeTruthy()
  expect(host.querySelector('[data-testid="calc-method"]')).toBeNull()
  expect(host.querySelector('.calc-table, .calc-checks, .calc-steps')).toBeNull()
})

it('renders the additive scan fields when present and nothing when absent', async () => {
  const calc = { ...scanReasoning.calc!,
    scale_proof: [{ page: 1, method: 'printed-ratio', m_per_px: 0.0123, spread_pct: 2.5, available_candidates: [{ method: 'door-prior', m_per_px: 0.012, formula: '0.9 / px' }] }],
    inventory_rows: [{ item_id: 'a', label: 'door', values: { origin: 'det', score: 0.91 } }, { item_id: 'b', label: 'door', values: { alternative: true } }],
    reader: { model_confidence: 0.7, calculations: [{}], tool_calls: [{}, {}], note: 'self-reported' }, unavailable: ['No second-look count.'] }
  await act(async () => root.render(<CalculationPanel reasoning={{ ...scanReasoning, calc }} onClose={() => {}} />))
  for (const id of ['scale', 'inventory', 'reader', 'unavailable']) expect(host.querySelector(`[data-section="${id}"]`), id).toBeTruthy()
  expect(host.querySelector('[data-section="inventory"]')?.textContent).toContain('not counted')
  await act(async () => root.render(<CalculationPanel reasoning={scanReasoning} onClose={() => {}} />))
  expect(host.querySelector('[data-section="scale"], [data-section="reader"]')).toBeNull()
})

it('folds supporting steps behind "Show all N steps", by level or by count', async () => {
  const base = scanReasoning.calc!
  const mk = (n: number, level?: (i: number) => 'main' | 'detail') => Array.from({ length: n }, (_, i) => ({ id: `s${i}`, label: `Step ${i}`, expr: 'x', value: i, unit: 'count', inputs: [], ...(level ? { level: level(i) } : {}) }))
  await act(async () => root.render(<CalculationPanel reasoning={{ ...scanReasoning, calc: { ...base, steps: mk(30) } }} onClose={() => {}} />))
  expect(host.querySelectorAll('.calc-steps')[0].children.length).toBe(4)
  expect(host.querySelector('[data-testid="calc-more-steps"] summary')?.textContent).toContain('Show 26 supporting steps')
  await act(async () => root.render(<CalculationPanel reasoning={{ ...scanReasoning, calc: { ...base, steps: mk(30, (i) => i < 3 ? 'main' : 'detail') } }} onClose={() => {}} />))
  expect(host.querySelectorAll('.calc-steps')[0].children.length).toBe(3)
  await act(async () => root.render(<CalculationPanel reasoning={{ ...scanReasoning, calc: { ...base, steps: mk(4) } }} onClose={() => {}} />))
  expect(host.querySelector('[data-testid="calc-more-steps"]')).toBeNull()
})

import claimsCalc from '../lib/__fixtures__/claims-calc.json'
it('claims calc: shows claim list with status chips, check line, crop, click-to-box, collapsed details', async () => {
  const onFocus = vi.fn()
  const reasoning = { steps: [], calc: claimsCalc, confidence: { label: 'Cross-checked', pct: 80, reason: 'r', improve: null } } as unknown as Parameters<typeof CalculationPanel>[0]['reasoning']
  await act(async () => root.render(<CalculationPanel reasoning={reasoning} onClose={() => {}} onFocus={onFocus} />))
  expect(host.querySelectorAll('.calc-claims > li').length).toBeGreaterThan(0)
  expect(host.querySelector('.calc-claim-status.is-verified')).toBeTruthy()
  expect(host.querySelector('.calc-claim-check')?.textContent).toBeTruthy()
  expect(host.querySelector('.calc-crop')).toBeTruthy()
  await act(async () => host.querySelector<HTMLButtonElement>('.calc-claims .calc-source-link')!.click())
  expect(onFocus).toHaveBeenCalled()
})

import { stepRows, meaningfulPath } from '../lib/calc-view'
it('stepRows drops no-op rounding and repeated method text, and folds repeated steps', () => {
  const st = (id: string, label: string, expr: string, value: number | null, extra = {}) => ({ id, label, expr, value, unit: 'count', inputs: [], level: 'main' as const, ...extra })
  const steps = [
    st('r', 'Result', 'round(22.0, 0)', 22, { note: 'Because of the filters.' }),
    st('a', 'Detections · wall', 'sum', 22), st('b', 'Detections · door', 'sum', 3), st('c', 'Detections · room', 'sum', 5),
    st('m', 'Margin · x', 'max', 0), ...Array.from({ length: 5 }, (_, i) => st(`n${i}`, 'Net wall surface', 'a − b', i)),
    st('k', 'Keep', 'a + b', 4.6, { note: 'because of the filters' }),
  ]
  const { main } = stepRows({ steps }, { why_chosen: 'Because of the filters.' })
  expect(main.map((r) => r.kind)).toEqual(['class', 'group', 'step'])
  expect(main[0].kind === 'class' && main[0].parts.map((p) => p.name)).toEqual(['wall', 'door', 'room'])
  expect(main[2].kind === 'step' && main[2].step.note).toBeUndefined()
})
it('meaningfulPath ignores the trivial page → method chain', () => {
  expect(meaningfulPath([{ label: 'Cited source page', relation: 'source of answer evidence' }, { label: 'Count', kind: 'calculation', relation: 'method used for this answer' }])).toHaveLength(0)
})

it('does not crash on a null result value or sparse steps (door answer payload)', async () => {
  const bad = { formula: 'doors = count', result: { value: null, unit: 'count' }, steps: [{ id: 's1', label: 'Count', value: null }], rows: [{ id: 'r', values: null }], checks: null } as unknown as Calculation
  const errors: unknown[] = []
  const spy = vi.spyOn(console, 'error').mockImplementation((e) => { errors.push(e) })
  await act(async () => root.render(<CalculationPanel reasoning={{ ...scanReasoning, calc: bad, graph_path: undefined }} onClose={() => {}} />))
  spy.mockRestore()
  expect(host.querySelector('[data-testid="calc-formula"]')).toBeTruthy()
  expect(errors.filter((e) => !String(e).includes('unique "key"'))).toEqual([])
})

it('error boundary shows a fallback instead of blanking the app', async () => {
  const Boom = (): never => { throw new Error('Cannot convert undefined or null to object') }
  const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
  await act(async () => root.render(<ErrorBoundary fallback={<p>Could not render this calculation</p>}><Boom /></ErrorBoundary>))
  spy.mockRestore()
  expect(host.textContent).toContain('Could not render this calculation')
})
