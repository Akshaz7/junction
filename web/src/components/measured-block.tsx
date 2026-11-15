import type { Answer, Calculation, Citation, ReasoningStep } from '../lib/types'
import { fmt, withUnit } from '../lib/calc-view'

/** Answers in these units get a "How it was measured" block. */
const MEASURE_UNITS = new Set(['m', 'mm', 'm2', 'm²'])

export type MeasureKey = 'source' | 'scale' | 'formula' | 'sure'
export interface MeasureLine { key: MeasureKey; label: string; text: string; cite?: number | null }

const LABEL: Record<MeasureKey, string> = { source: 'Source', scale: 'Scale', formula: 'Formula', sure: 'How sure' }
/** Engine step titles that belong in the block (reasoning.steps). */
const TITLE: Record<MeasureKey, RegExp> = { source: /^source$/i, scale: /^scale$/i, formula: /^(formula|calculation)$/i, sure: /^how sure$/i }
/** Step ids engine/measure_why.py gives these steps. */
const STEP_ID: Record<MeasureKey, string> = { source: 'why-source', scale: 'why-scale', formula: 'why-calc', sure: 'why-sure' }
const ORDER: MeasureKey[] = ['source', 'scale', 'formula', 'sure']

export const IFC_SOURCE = 'From the IFC model (metres)'

/** Readable names for scale methods (scale_proof step labels). Unknown methods keep their own name. */
const METHOD_WORDS: Record<string, string> = {
  'door prior': 'Door widths', ifc: 'IFC model', dimension: 'Printed dimension', 'printed ratio': 'Printed scale', ratio: 'Printed scale',
  'scale bar': 'Scale bar', scalebar: 'Scale bar', 'known size': 'Known size', 'dxf units': 'CAD file units', 'printed areas': 'Printed room areas',
}
const methodWord = (label: string) => METHOD_WORDS[label.toLowerCase().replace(/[-_]+/g, ' ')] ?? label.charAt(0).toUpperCase() + label.slice(1)

export function isMeasurement(answer: Answer): boolean {
  const calc = answer.reasoning?.calc
  const unit = answer.answer?.unit ?? (calc && calc.kind !== 'claims' ? calc.result?.unit : undefined)
  return !!unit && MEASURE_UNITS.has(unit)
}

/** The engine's own Source / Scale / Formula / How sure steps, by title. */
export function measureSteps(steps: ReasoningStep[] | undefined): Partial<Record<MeasureKey, ReasoningStep>> {
  const out: Partial<Record<MeasureKey, ReasoningStep>> = {}
  for (const step of steps ?? []) {
    const id = (step as ReasoningStep & { id?: string }).id
    const key = ORDER.find((k) => id === STEP_ID[k]) ?? ORDER.find((k) => TITLE[k].test((step.title ?? '').trim()))
    if (key && !out[key] && step.text?.trim()) out[key] = step
  }
  return out
}

/** The answer's numbers come straight from IFC elements (element citations or IFC rows), not from drawing pixels. */
function fromIfc(answer: Answer, calc: Calculation | undefined): boolean {
  if (answer.citations.length && answer.citations.every((c) => c.kind === 'element')) return true
  return !!calc?.rows?.length && calc.rows.every((row) => row.source?.origin === 'ifc')
}

type Proof = NonNullable<Calculation['scale_proof']>[number]
type ProofStep = NonNullable<Proof['steps']>[number]

/** The scale proof for the page the answer cites; else the only page. */
function proofFor(calc: Calculation | undefined, citation: Citation | undefined): Proof | undefined {
  const proofs = calc?.scale_proof ?? []
  if (citation) {
    const hit = proofs.find((p) => (p.doc_id == null || p.doc_id === citation.doc_id) && p.page === citation.page)
    if (hit) return hit
  }
  return proofs.length === 1 ? proofs[0] : undefined
}

/** "0.9 m ÷ 31 px (median of 11 door icons)" for door widths; else the recorded expression with its single inputs. */
function basisText(step: ProofStep): string {
  const inputs = step.inputs ?? []
  const label = (step.label ?? '').toLowerCase()
  if (label === 'door prior') {
    const assumed = inputs.find((i) => i.unit === 'm')
    const n = step.sample_count ?? inputs.filter((i) => i.unit === 'px').length
    if (assumed && step.median_width_px != null) return `${withUnit(assumed.value, 'm')} door ÷ ${fmt(step.median_width_px)} px (median of ${n} door icons)`
  }
  const expr = (step.expr ?? '').replace(/^scale\s*=\s*/i, '')
  const names = new Map<string, number>()
  for (const i of inputs) names.set(i.name, (names.get(i.name) ?? 0) + 1)
  const values = inputs.filter((i) => names.get(i.name) === 1 && (typeof i.value === 'number' || typeof i.value === 'string')).map((i) => `${i.name} ${withUnit(i.value, i.unit)}`)
  return [expr, values.length ? values.join(', ') : ''].filter(Boolean).join(': ')
}

/** Scale line from calc.scale_proof: the candidate that equals the scale used, with method, m/px, basis and confidence. */
function scaleFromProof(proof: Proof | undefined): { text: string; ifc: boolean } | null {
  if (!proof) return null
  const used = proof.result?.value ?? proof.m_per_px
  if (typeof used !== 'number' || !Number.isFinite(used) || used <= 0) return null
  const step = (proof.steps ?? []).find((s) => typeof s.value === 'number' && Math.abs(s.value / used - 1) < 1e-6)
  const method = step?.label ?? proof.method
  if (method && methodWord(method) === 'IFC model') return { text: IFC_SOURCE, ifc: true }
  const conf = step?.confidence ?? proof.confidence
  const parts = [method ? methodWord(method) : null, `${fmt(used)} m/px`, step ? basisText(step) : 'inputs not recorded',
    typeof conf === 'number' && Number.isFinite(conf) ? `confidence ${fmt(conf, 2)}` : step?.uncertainty_known === false ? 'uncertainty not measured' : null]
  return { text: parts.filter(Boolean).join(' · '), ifc: false }
}

/**
 * Compact justification for a length or area answer. The engine's own Source / Scale / Formula / How sure steps win;
 * otherwise the scale comes from calc.scale_proof (drawings) or the IFC element citations, and the formula from
 * reasoning.arithmetic. Lines with no data are left out; nothing is guessed.
 */
export function measurementLines(answer: Answer): MeasureLine[] {
  const reasoning = answer.reasoning
  if (!reasoning || !isMeasurement(answer)) return []
  const calc = reasoning.calc && reasoning.calc.kind !== 'claims' ? reasoning.calc : undefined
  const steps = measureSteps(reasoning.steps)
  const lines: MeasureLine[] = []
  const add = (key: MeasureKey, text: string | undefined | null, cite?: number | null) => { if (text?.trim()) lines.push({ key, label: LABEL[key], text: text.trim(), cite }) }
  const ifcBySource = steps.source ? /\bIFC\b/.test(steps.source.text) : fromIfc(answer, calc)
  const proofScale = !steps.scale && !ifcBySource ? scaleFromProof(proofFor(calc, answer.citations[0])) : null
  const ifc = ifcBySource || !!proofScale?.ifc
  add('source', steps.source?.text ?? (ifc ? IFC_SOURCE : null), steps.source?.cite)
  add('scale', steps.scale?.text ?? (ifc ? null : proofScale?.text), steps.scale?.cite)
  add('formula', steps.formula?.text ?? reasoning.arithmetic?.find((a) => a.text?.trim())?.text, steps.formula?.cite)
  add('sure', steps.sure?.text, steps.sure?.cite)
  return lines
}

export function MeasuredBlock({ lines, citations, onOpenCitation }: { lines: MeasureLine[]; citations: Citation[]; onOpenCitation: (citation: Citation) => void }) {
  if (!lines.length) return null
  return <div className="evidence-measured" data-testid="evidence-measured" aria-label="How it was measured">
    <h4>How it was measured</h4>
    <dl>{lines.map((line) => {
      const citation = line.cite == null ? undefined : citations.find((c) => c.n === line.cite)
      return <div key={line.key} data-key={line.key}>
        <dt>{line.label}</dt>
        <dd>{citation
          ? <button type="button" className="evidence-measured-link" aria-label={`${line.label}: ${line.text}. Open citation ${citation.n}`} onClick={() => onOpenCitation(citation)}>{line.text} <span className="citation-chip" aria-hidden="true">{citation.n}</span></button>
          : line.text}</dd>
      </div>
    })}</dl>
  </div>
}
