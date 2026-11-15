// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { EvidenceCard } from './evidence-card'
import { IFC_SOURCE, measurementLines } from './measured-block'
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

const conf = { label: 'Estimate', pct: 40, reason: 'Not independently verified.', improve: null }
const doorInput = (n: number, px: number) => ({ name: 'door icon width', value: px, unit: 'px', source: { doc_id: 'plan', page: 1, item_id: `door-00${n}` } })

/** Trimmed from a real answer: "What is the total floor area?" on a scanned drawing (scale from door widths, no explicit measure steps). */
const drawingArea = {
  answer: { text_md: '**The total floor area is about 62.3 m².** [1]', value: 62.33, unit: 'm2', confidence: 0.4, abstained: false },
  citations: [{ n: 1, doc_id: 'plan', page: 1, kind: 'region', bbox_px: [0, 0, 10, 10], item_ids: [], quote: null }],
  reasoning: {
    steps: [
      { kind: 'found', title: 'Found', text: '8 rooms on the scanned drawing, each one numbered', cite: 1 },
      { kind: 'calculated', title: 'Calculated', text: 'Add the source quantities: 0.6 + 21.55 + 8.02 = 62.33 m².', cite: null },
    ],
    confidence: conf,
    calc: {
      formula: 'total = Σ(source quantities)', steps: [], rows: [], checks: [],
      result: { value: 62.33, unit: 'm2', rounded_as: '2 decimal places' },
      margin: { value: null, unit: 'm2', pct: null, why: 'Scale confidence 0.3 (not an error bound).', sources: [] },
      scale_proof: [
        { doc_id: 'other', page: 1, result: { value: 0.5, unit: 'm/px' }, steps: [{ id: 'x', label: 'door prior', expr: 'scale = assumed door width / median(door icon widths)', value: 0.5, unit: 'm/px', inputs: [] }] },
        { doc_id: 'plan', page: 1, formula: 'drawing distance in metres = pixel distance × scale', derivation_complete: true,
          result: { value: 0.02903225806451613, unit: 'm/px', rounded_as: 'stored precision' },
          steps: [{ id: 'scale-1-1', label: 'door prior', expr: 'scale = assumed door width / median(door icon widths)', value: 0.02903225806451613, unit: 'm/px',
            sample_count: 11, median_width_px: 31, uncertainty_known: false,
            inputs: [{ name: 'assumed door width', value: 0.9, unit: 'm', source: { doc_id: 'plan', page: 1 } }, doorInput(1, 34), doorInput(2, 31), doorInput(3, 31)] }] },
      ],
    },
  },
} as unknown as Answer

/** Trimmed from a real answer: "How wide is the main entrance door?" on the AC20 IFC model (rendered pages carry an unrelated door-prior scale). */
const ifcWidth = {
  answer: { text_md: '**The main entrance door (Tür-019) is 2.0 m wide.** [1]', value: 2.0, unit: 'm', confidence: 0.7, abstained: false },
  citations: [{ n: 1, doc_id: 'ifc_bench__ac20-arc', page: 1, kind: 'element', bbox_px: null, item_ids: ['18PQUIFELEARLM4c0brquf'], quote: '1 matching doors (external)' }],
  reasoning: {
    steps: [{ kind: 'found', title: 'Found', text: 'One door on Erdgeschoss in the building model (IFC)', cite: 1 }],
    confidence: conf,
    calc: {
      formula: 'total = Σ(source quantities)', steps: [], checks: [],
      rows: [{ item_id: '18PQUIFELEARLM4c0brquf', label: 'Tür-019', values: { kind: 'door' }, source: { doc_id: 'ifc_bench__ac20-arc', origin: 'ifc', kind: 'element' } }],
      result: { value: 2.0, unit: 'm', rounded_as: '1 decimal places' },
      margin: { value: null, unit: 'm', pct: null, why: 'Not recorded.', sources: [] },
      scale_proof: [{ doc_id: 'ifc_bench__ac20-arc', page: 1, result: { value: 0.018103, unit: 'm/px' },
        steps: [{ id: 'scale-1-1', label: 'door prior', expr: 'scale = assumed door width / median(door icon widths)', value: 0.016289592760180997, unit: 'm/px', inputs: [] }] }],
    },
  },
} as unknown as Answer

/** A distance answer carrying the engine's explicit Source / Scale / Formula / How sure steps. */
const distance = {
  answer: { text_md: '**The kitchen and the bathroom are about 4.5 m apart, centre to centre.** [1]', value: 4.5, unit: 'm', confidence: 0.4, abstained: false },
  citations: [{ n: 1, doc_id: 'plan', page: 1, kind: 'region', bbox_px: [0, 0, 10, 10], item_ids: [], quote: null }],
  reasoning: {
    steps: [
      { kind: 'found', title: 'Found', text: '2 rooms on the scanned drawing: kitchen, KPH', cite: 1 },
      { kind: 'read', title: 'Source', text: 'Drawing outline: room centres from the detected room outlines', cite: 1 },
      { kind: 'measured', title: 'Scale', text: 'Door widths · 0.02903 m/px · 0.9 m door ÷ 31 px median of 11 doors · confidence 0.3', cite: null },
      { kind: 'calculated', title: 'Formula', text: '155.06 px × 0.02903 m/px = 4.50 m', cite: null },
      { kind: 'checked', title: 'How sure', text: 'About ± 0.4 m (door sizes vary about 9%)', cite: null },
    ],
    confidence: conf,
    calc: { formula: 'pixel length × scale', steps: [], rows: [], checks: [], result: { value: 4.5, unit: 'm', rounded_as: '1 decimal places' }, margin: { value: null, unit: 'm', pct: null, why: '', sources: [] } },
  },
} as unknown as Answer

const lineMap = (a: Answer) => Object.fromEntries(measurementLines(a).map((l) => [l.key, l.text]))

describe('measurementLines', () => {
  it('drawing area: scale from the proof for the cited page (method, m/px, basis, uncertainty); no IFC line', () => {
    const lines = lineMap(drawingArea)
    expect(lines.source).toBeUndefined()
    expect(lines.scale).toBe('Door widths · 0.02903 m/px · 0.9 m door ÷ 31 px (median of 11 door icons) · uncertainty not measured')
    expect(lines.formula).toBeUndefined()
  })

  it('IFC width: says it comes from the IFC model and never shows a drawing scale', () => {
    expect(lineMap(ifcWidth)).toEqual({ source: IFC_SOURCE })
  })

  it('distance: the engine steps win, in Source / Scale / Formula / How sure order', () => {
    const lines = measurementLines(distance)
    expect(lines.map((l) => l.label)).toEqual(['Source', 'Scale', 'Formula', 'How sure'])
    expect(lines[2].text).toBe('155.06 px × 0.02903 m/px = 4.50 m')
    expect(lines[0].cite).toBe(1)
  })

  it('matches the titles and ids engine/measure_why.py emits (Source, Scale, Calculation, How sure)', () => {
    const steps = [
      { id: 'why-source', kind: 'read', title: 'Source', text: 'Drawing outline', cite: 1 },
      { id: 'why-scale', kind: 'measured', title: 'Scale', text: 'Door widths · 0.02903 m/px' },
      { id: 'why-calc', kind: 'calculated', title: 'Calculation', text: '155.06 px × 0.02903 m/px = 4.50 m' },
      { id: 'why-sure', kind: 'checked', title: 'How sure', text: 'About ± 0.4 m' },
    ]
    const a = { ...distance, reasoning: { ...distance.reasoning!, steps } } as unknown as Answer
    expect(lineMap(a)).toEqual({ source: 'Drawing outline', scale: 'Door widths · 0.02903 m/px', formula: '155.06 px × 0.02903 m/px = 4.50 m', sure: 'About ± 0.4 m' })
  })

  it('uses the arithmetic text as the formula when there is no Formula step', () => {
    const withArith = { ...drawingArea, reasoning: { ...drawingArea.reasoning!, arithmetic: [{ formula: 'sum', text: '21.55 + 8.02 + 32.76 = 62.33 m²', terms: [], result: 62.33, unit: 'm2' }] } } as Answer
    expect(lineMap(withArith).formula).toBe('21.55 + 8.02 + 32.76 = 62.33 m²')
  })

  it('a step that repeats the formula line is shown once, in the block', async () => {
    const text = 'Add the source quantities: 0.6 + 21.55 + 8.02 = 62.33 m².'
    const withArith = { ...drawingArea, reasoning: { ...drawingArea.reasoning!, arithmetic: [{ formula: 'sum', text, terms: [], result: 62.33, unit: 'm2' }] } } as Answer
    await act(async () => root.render(<EvidenceCard answer={withArith} onOpenCitation={vi.fn()} />))
    expect(host.querySelector('[data-testid="evidence-measured"]')!.textContent).toContain(text)
    expect([...host.querySelectorAll('.evidence-steps li')].map((li) => li.textContent)).toEqual([expect.stringContaining('8 rooms')])
  })

  it('a stored scale with no matching derivation says its inputs were not recorded', () => {
    const calc = drawingArea.reasoning!.calc as NonNullable<Answer['reasoning']>['calc'] & { scale_proof: unknown[] }
    const stored = { ...drawingArea, reasoning: { ...drawingArea.reasoning!, calc: { ...calc, scale_proof: [{ doc_id: 'plan', page: 1, method: 'printed-ratio', result: { value: 0.01, unit: 'm/px' }, steps: [] }] } } } as unknown as Answer
    expect(lineMap(stored).scale).toBe('Printed scale · 0.01 m/px · inputs not recorded')
  })

  it('nothing for counts, nothing when no measurement data exists', () => {
    expect(measurementLines({ ...drawingArea, answer: { ...drawingArea.answer, unit: 'count', value: 8 } } as Answer)).toEqual([])
    const bare = { ...distance, citations: [], reasoning: { steps: [{ kind: 'found', title: 'Found', text: 'Two rooms' }], confidence: conf } } as unknown as Answer
    expect(measurementLines(bare)).toEqual([])
  })
})

describe('EvidenceCard with a measurement', () => {
  it('drawing area: shows the block above the steps, keeps Show calculation', async () => {
    await act(async () => root.render(<EvidenceCard answer={drawingArea} onOpenCitation={vi.fn()} onShowCalculation={vi.fn()} />))
    const block = host.querySelector('[data-testid="evidence-measured"]')!
    expect(block.querySelector('h4')!.textContent).toBe('How it was measured')
    expect(block.textContent).toContain('0.02903 m/px')
    expect(host.querySelectorAll('.evidence-steps li').length).toBe(2)
    expect(block.compareDocumentPosition(host.querySelector('.evidence-steps')!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(host.querySelector('.evidence-calc-link')!.textContent).toBe('Show calculation')
  })

  it('IFC width: one Source line, no scale', async () => {
    await act(async () => root.render(<EvidenceCard answer={ifcWidth} onOpenCitation={vi.fn()} />))
    const block = host.querySelector('[data-testid="evidence-measured"]')!
    expect([...block.querySelectorAll('dt')].map((d) => d.textContent)).toEqual(['Source'])
    expect(block.textContent).toContain(IFC_SOURCE)
    expect(block.textContent).not.toContain('m/px')
  })

  it('distance: engine steps move into the block (not listed twice); a cited line opens its citation', async () => {
    const onOpen = vi.fn()
    await act(async () => root.render(<EvidenceCard answer={distance} onOpenCitation={onOpen} />))
    const block = host.querySelector('[data-testid="evidence-measured"]')!
    expect([...block.querySelectorAll('dt')].map((d) => d.textContent)).toEqual(['Source', 'Scale', 'Formula', 'How sure'])
    const listed = [...host.querySelectorAll('.evidence-steps li')].map((li) => li.textContent)
    expect(listed).toHaveLength(1)
    expect(listed[0]).toContain('2 rooms on the scanned drawing')
    await act(async () => block.querySelector<HTMLButtonElement>('button.evidence-measured-link')!.click())
    expect(onOpen).toHaveBeenCalledWith(distance.citations[0])
  })

  it('a count answer keeps its Source-titled steps in the list and shows no block', async () => {
    const count = { ...distance, answer: { ...distance.answer, unit: 'count', value: 2 } } as Answer
    await act(async () => root.render(<EvidenceCard answer={count} onOpenCitation={vi.fn()} />))
    expect(host.querySelector('[data-testid="evidence-measured"]')).toBeNull()
    expect(host.querySelectorAll('.evidence-steps li').length).toBe(5)
  })
})
