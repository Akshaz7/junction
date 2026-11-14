import { useMemo, useState, type ReactNode } from 'react'
import { ArrowDown, ArrowUp, ChevronRight, X } from 'lucide-react'
import { Button } from './ui'
import type { Calculation, Reasoning } from '../lib/types'
import { columnKeys, columnLabel, fmt, focusOf, pageRows, signed, sortRows, sourceText, totalsOf, withUnit, type FocusTarget, type RowSort } from '../lib/calc-view'
import './calc-panel.css'

const PAGE = 15

function Section({ title, hint, open = true, children, id }: { title: string; hint?: string; open?: boolean; children: ReactNode; id: string }) {
  return <details className="calc-section" open={open} data-section={id}>
    <summary><ChevronRight size={13} aria-hidden="true" /><span>{title}</span>{hint && <small>{hint}</small>}</summary>
    <div className="calc-section-body">{children}</div>
  </details>
}

function SourceLink({ source, docTitle, onFocus }: { source: Calculation['rows'][number]['source']; docTitle?: (id: string) => string; onFocus?: (target: FocusTarget) => void }) {
  const target = focusOf(source), text = sourceText(source, docTitle)
  return <span className="calc-source">
    {target && onFocus
      ? <button type="button" className="calc-source-link" onClick={() => onFocus(target)} aria-label={`Show on the drawing: ${text}`}>{text}</button>
      : <span>{text}</span>}
    {source?.crop && <img className="calc-crop" src={source.crop} alt="" loading="lazy" />}
  </span>
}

function RowsTable({ calc, onFocus, docTitle }: { calc: Calculation; onFocus?: (t: FocusTarget) => void; docTitle?: (id: string) => string }) {
  const [sort, setSort] = useState<RowSort>(null)
  const [page, setPage] = useState(0)
  const keys = useMemo(() => columnKeys(calc.rows), [calc.rows])
  const totals = useMemo(() => totalsOf(calc), [calc])
  const sorted = useMemo(() => sortRows(calc.rows, sort), [calc.rows, sort])
  const view = pageRows(sorted, page, PAGE)
  const toggle = (key: string) => { setPage(0); setSort((old) => old?.key !== key ? { key, dir: 'asc' } : old.dir === 'asc' ? { key, dir: 'desc' } : null) }
  const head = (key: string, label: string, numeric: boolean) => {
    const on = sort?.key === key
    return <th scope="col" className={numeric ? 'num' : undefined} aria-sort={on ? (sort!.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
      <button type="button" onClick={() => toggle(key)}>{label}{on && (sort!.dir === 'asc' ? <ArrowUp size={11} aria-hidden="true" /> : <ArrowDown size={11} aria-hidden="true" />)}</button>
    </th>
  }
  return <>
    <div className="calc-table-wrap"><table className="calc-table" aria-label="Per-element figures">
      <thead><tr>{head('__label', 'Element', false)}{keys.map((k) => head(k, columnLabel(k), true))}<th scope="col">Source</th></tr></thead>
      <tbody>{view.rows.map((row) => <tr key={row.item_id}>
        <th scope="row">{row.label}</th>
        {keys.map((k) => <td key={k} className="num">{fmt(row.values?.[k])}</td>)}
        <td><SourceLink source={row.source} docTitle={docTitle} onFocus={onFocus} /></td>
      </tr>)}</tbody>
      <tfoot><tr><th scope="row">Total ({totals.count} {totals.count === 1 ? 'element' : 'elements'})</th>{keys.map((k) => <td key={k} className="num">{k in totals.sums ? fmt(totals.sums[k]) : ''}</td>)}<td /></tr></tfoot>
    </table></div>
    {totals.note && <p className={`calc-reconcile ${totals.reconciles ? 'is-ok' : 'is-off'}`} data-testid="calc-reconcile">{totals.note}</p>}
    {view.pages > 1 && <nav className="calc-pager" aria-label="Table pages">
      <button type="button" disabled={view.page === 0} onClick={() => setPage(view.page - 1)}>Previous</button>
      <span>Page {view.page + 1} of {view.pages}</span>
      <button type="button" disabled={view.page >= view.pages - 1} onClick={() => setPage(view.page + 1)}>Next</button>
    </nav>}
  </>
}

/** The technical view of "How we know": every step with its numbers, inputs and sources, the per-element table, checks, margin and confidence. */
export function CalculationPanel({ reasoning, title, onClose, onFocus, docTitle }: {
  reasoning: Reasoning; title?: string; onClose: () => void; onFocus?: (target: FocusTarget) => void; docTitle?: (id: string) => string
}) {
  const calc = reasoning.calc
  const { confidence } = reasoning
  const margin = calc?.margin ?? reasoning.margin
  const result = calc?.result
  return <aside className="viewer-calc-panel" aria-label="Calculation" data-testid="calc-panel">
    <header>
      <div><strong>Calculation</strong>{title && <small>{title}</small>}</div>
      <Button variant="ghost" size="icon" aria-label="Close calculation" onClick={onClose}><X size={16} /></Button>
    </header>
    <div className="calc-content">
      {calc?.formula && <div className="calc-formula" data-testid="calc-formula">
        <code>{calc.formula}</code>
        {result && typeof result.value === 'number' && <p className="calc-result"><span>=</span> <b>{withUnit(result.value, result.unit)}</b>{result.rounded_as && <small>rounded to {result.rounded_as}</small>}</p>}
        {result && typeof result.value !== 'number' && <p className="calc-result">{Object.entries(result.value).map(([k, v]) => <span key={k}><b>{fmt(v)}</b> <small>{k}</small> </span>)}</p>}
      </div>}
      {calc?.status === 'incomplete' && <p className="calc-warning" role="status">This calculation could not be reproduced in full.{calc.issues?.length ? ` ${calc.issues.join(' ')}` : ''}</p>}
      {!calc && <p className="calc-none">No calculation was recorded for this answer. The steps are listed on the card.</p>}

      {!!reasoning.graph_path?.length && <Section id="path" title="Chain of evidence">
        <ol className="calc-path" aria-label="Chain of evidence">{reasoning.graph_path.map((node, i) => <li key={i}>
          {i > 0 && <span className="calc-edge" aria-hidden="true">{node.relation ?? '→'}</span>}
          {node.item_id && onFocus ? <button type="button" className="calc-node" onClick={() => onFocus({ item_id: node.item_id!, ...(node.doc_id ? { doc_id: node.doc_id } : {}), ...(node.page != null ? { page: node.page } : {}) })}>{node.label}</button> : <span className="calc-node">{node.label}</span>}
          {node.kind && <small>{node.kind}</small>}
        </li>)}</ol>
      </Section>}

      {!!calc?.steps.length && <Section id="steps" title="Steps" hint={`${calc.steps.length}`}>
        <ol className="calc-steps">{calc.steps.map((step, i) => <li key={step.id} data-step={step.id}>
          <div className="calc-step-head"><span className="calc-index">{i + 1}</span><strong>{step.label}</strong></div>
          <p className="calc-expr"><code>{step.expr}</code>{step.value != null && <> <span className="calc-eq">=</span> <b className="calc-value">{withUnit(step.value, step.unit)}</b></>}</p>
          {step.note && <p className="calc-note">{step.note}</p>}
          {!!step.inputs.length && <details className="calc-inputs"><summary>Inputs ({step.inputs.length})</summary>
            <table aria-label={`Inputs of ${step.label}`}><thead><tr><th scope="col">Input</th><th scope="col" className="num">Value</th><th scope="col">Source</th></tr></thead>
              <tbody>{step.inputs.map((input, k) => <tr key={k}><th scope="row">{input.name}</th><td className="num">{withUnit(input.value, input.unit)}</td><td><SourceLink source={input.source} docTitle={docTitle} onFocus={onFocus} /></td></tr>)}</tbody></table>
          </details>}
        </li>)}</ol>
      </Section>}

      {!!calc?.rows.length && <Section id="rows" title="Per-element figures" hint={`${calc.rows.length}`}><RowsTable calc={calc} onFocus={onFocus} docTitle={docTitle} /></Section>}

      {!!calc?.checks.length && <Section id="checks" title="Checks" hint="second methods">
        <table className="calc-checks" aria-label="Checks"><thead><tr><th scope="col">Method</th><th scope="col" className="num">Value</th><th scope="col">Agrees</th><th scope="col" className="num">Diff</th></tr></thead>
          <tbody>{calc.checks.map((check, i) => <tr key={i}>
            <th scope="row">{check.method}</th><td className="num">{check.value != null ? fmt(check.value) : '-'}</td>
            <td>{check.agrees == null ? '-' : <span className={`calc-tag ${check.agrees ? 'is-ok' : 'is-off'}`}>{check.agrees ? 'agrees' : 'differs'}</span>}</td>
            <td className="num">{check.diff_pct != null ? `${fmt(check.diff_pct, 2)}%` : '-'}</td></tr>)}</tbody></table>
      </Section>}

      {margin && <Section id="margin" title="Margin of error">
        {margin.value != null && Number.isFinite(margin.value)
          ? <p className="calc-margin"><b>± {withUnit(margin.value, margin.unit)}</b>{margin.pct != null && <> <span>(± {fmt(margin.pct, 2)}%)</span></>}</p>
          : <p className="calc-margin">Not known</p>}
        <p className="calc-note">{margin.why}</p>
        {margin.sources.length > 0 && <p className="calc-note">Based on: {margin.sources.join('; ')}</p>}
      </Section>}

      <Section id="confidence" title="Confidence" hint={confidence.pct != null ? `${confidence.label} · ${confidence.pct}%` : confidence.label}>
        <p className="calc-note">{confidence.reason}</p>
        {!!confidence.factors?.length && <table className="calc-factors" aria-label="What moved the confidence figure"><tbody>
          {confidence.factors.map((f, i) => <tr key={i}><th scope="row">{f.label}{f.note && <small>{f.note}</small>}</th><td className="num">{f.base ? 'start' : `${signed(f.delta)} pts`}</td></tr>)}
          {confidence.pct != null && <tr className="calc-factor-total"><th scope="row">Confidence</th><td className="num">{confidence.pct}%</td></tr>}
        </tbody></table>}
        {confidence.calibration && <p className="calc-note">Calibration: {confidence.calibration.correct} of {confidence.calibration.n} correct · {confidence.calibration.source}{confidence.calibration.interval_95 ? ` · 95% interval ${fmt(confidence.calibration.interval_95[0], 1)} to ${fmt(confidence.calibration.interval_95[1], 1)}` : ''}</p>}
        {confidence.improve && <p className="calc-note">To verify: {confidence.improve}</p>}
      </Section>
    </div>
  </aside>
}
