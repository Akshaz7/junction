// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { EvidenceCard } from './evidence-card'
import type { Answer } from '../lib/types'

let host: HTMLDivElement
let root: Root
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
})
afterEach(async () => { await act(async () => root.unmount()); host.remove() })

const citation = { n: 1, doc_id: 'd', page: 1, kind: 'region' as const, bbox_px: null, item_ids: [], quote: null }
const answer = {
  citations: [citation],
  reasoning: {
    steps: [
      { kind: 'found', title: 'Found', text: 'Room Küche 2.02', cite: 1 },
      { kind: 'checked', title: 'Checked', text: 'Label agrees', ok: true },
    ],
    confidence: { label: 'Cross-checked', pct: 94, reason: 'Outline and label agree.', improve: null },
  },
} as unknown as Answer

it('renders steps and the confidence pill', async () => {
  await act(async () => root.render(<EvidenceCard answer={answer} onOpenCitation={vi.fn()} />))
  expect(host.querySelectorAll('li').length).toBe(2)
  expect(host.textContent).toContain('Room Küche 2.02')
  expect(host.querySelector('.evidence-pill')!.textContent).toBe('Cross-checked · 94%')
  expect(host.querySelector('.evidence-pill')!.getAttribute('aria-label')).toContain('94')
})

it('opens the matching citation when a step is clicked', async () => {
  const onOpen = vi.fn()
  await act(async () => root.render(<EvidenceCard answer={answer} onOpenCitation={onOpen} />))
  await act(async () => host.querySelector<HTMLButtonElement>('button.evidence-row')!.click())
  expect(onOpen).toHaveBeenCalledWith(citation)
  expect(host.querySelectorAll('button').length).toBe(1)
})

it('renders nothing without reasoning', async () => {
  await act(async () => root.render(<EvidenceCard answer={{ ...answer, reasoning: undefined }} onOpenCitation={vi.fn()} />))
  expect(host.innerHTML).toBe('')
})

it('shows the quantified margin, source, and element counts', async () => {
  const quantified = { ...answer, reasoning: { ...answer.reasoning!,
    margin: { value: 1.8, unit: 'm2', pct: 2.6, why: 'Measured scale spread.', sources: ['Drawing scale'] },
    based_on: { elements: 46, estimated: 0, unresolved: 0, text: 'Based on 46 elements from the model; 0 estimated.' },
  } }
  await act(async () => root.render(<EvidenceCard answer={quantified} onOpenCitation={vi.fn()} />))
  expect(host.textContent).toContain('Margin: ± 1.8 m² (± 2.6%)')
  expect(host.textContent).toContain('46 elements from the model; 0 estimated')
  expect(host.textContent).toContain('Sources: Drawing scale')
})

it('explains missing margins and hides an uncalibrated percentage', async () => {
  const unknown = { ...answer, reasoning: { ...answer.reasoning!, steps: [],
    confidence: { label: 'Estimate' as const, pct: null, reason: 'No measured accuracy is available.' },
    margin: { value: null, unit: 'm2', pct: null, why: 'Door-width variation is unknown.', sources: [] },
  } }
  await act(async () => root.render(<EvidenceCard answer={unknown} onOpenCitation={vi.fn()} />))
  expect(host.textContent).toContain('Margin not known — Door-width variation is unknown.')
  expect(host.querySelector('.evidence-pill')!.textContent).toBe('Estimate')
  expect(host.textContent).not.toMatch(/null|undefined|NaN/)
})

it('preserves a zero exact-count margin and names the calibration sample', async () => {
  const exact = { ...answer, reasoning: { ...answer.reasoning!,
    confidence: { ...answer.reasoning!.confidence, pct: 50, calibration: { correct: 1, n: 2, source: 'results/final/QA2/calibration.json' } },
    margin: { value: 0, unit: 'count', pct: 0, why: 'Exact source count.', sources: [] },
  } }
  await act(async () => root.render(<EvidenceCard answer={exact} onOpenCitation={vi.fn()} />))
  expect(host.textContent).toContain('Margin: ± 0 elements (± 0%)')
  expect(host.textContent).toContain('Calibration: 1/2')
})

it('clamps a long margin and sources line to two lines with a more toggle', async () => {
  const long = 'Historical mean absolute error and observed recount differences, ' + 'x'.repeat(200)
  const withMargin = { ...answer, reasoning: { ...answer.reasoning!, margin: { value: 1, unit: 'count', pct: 5, why: long, sources: [long], by_kind: {} } } } as unknown as Answer
  await act(async () => root.render(<EvidenceCard answer={withMargin} onOpenCitation={vi.fn()} />))
  expect(host.querySelectorAll('.evidence-clamp').length).toBeGreaterThan(0)
  const more = host.querySelector<HTMLButtonElement>('.evidence-more')!
  await act(async () => more.click())
  expect(more.textContent).toBe('less')
})
