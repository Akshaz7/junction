import type { Calculation, CalculationSource } from './types'

const valueText = (value: unknown): string => typeof value === 'string' ? value : JSON.stringify(value) ?? ''

function sourceText(source: CalculationSource): string {
  if (source.kind === 'step') return `Calculation step ${source.step_id}`
  return [source.doc_id, source.page ? `page ${source.page}` : '', source.item_id, source.bbox ? `box [${source.bbox.join(', ')}]` : '', source.artifact, source.field, source.text].filter(Boolean).join(' · ')
}

/** Complete audit for the existing Markdown and printable report paths. */
export function calculationLines(calc: Calculation): string[] {
  const lines = ['Calculation report', `Formula: ${calc.formula}`, `Audit: ${calc.status ?? 'not recorded'}`]
  for (const step of calc.steps) {
    lines.push(`${step.label} (${step.id}): ${step.expr} = ${valueText(step.value)} ${step.unit}`)
    for (const input of step.inputs) lines.push(`Input — ${input.name}: ${valueText(input.value)} ${input.unit}; source: ${sourceText(input.source)}`)
    if (step.note) lines.push(step.note)
  }
  lines.push('Per-element quantities')
  for (const row of calc.rows) lines.push(`${row.label} (${row.item_id}): ${valueText(row.values)}; source: ${sourceText(row.source)}`)
  lines.push(`Result: ${valueText(calc.result.value)} ${calc.result.unit} (${calc.result.rounded_as})`)
  for (const result of calc.result.additional ?? []) lines.push(`${result.label}: ${result.value} ${result.unit} (${result.rounded_as ?? 'as recorded'})`)
  for (const check of calc.checks) lines.push(`Check — ${check.method}: ${valueText(check.value)}${check.agrees === true ? ' (agrees)' : check.agrees === false ? ' (differs)' : ''}${check.diff_pct != null ? `, difference ${check.diff_pct}%` : ''}`)
  if (!calc.checks.length) lines.push('No independent calculation check recorded.')
  lines.push(`Margin: ${calc.margin.value ?? 'not quantified'} ${calc.margin.unit}; ${calc.margin.why}`)
  if (calc.margin.sources.length) lines.push(`Margin sources: ${calc.margin.sources.join('; ')}`)
  for (const issue of calc.issues ?? []) lines.push(`Unresolved evidence: ${issue}`)
  return lines
}
