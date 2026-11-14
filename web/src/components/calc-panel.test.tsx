// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { CalculationPanel } from './calc-panel'
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
