import { useMemo, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from 'react'
import { ArrowDown, ArrowLeft, ArrowUp, ChevronRight, Maximize2, Minimize2, X } from 'lucide-react'
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
    {source?.crop && (target && onFocus
      ? <button type="button" className="calc-crop-link" onClick={() => onFocus(target)} aria-label={`Show source crop on the drawing: ${text}`}><img className="calc-crop" src={source.crop} alt="Source region" loading="lazy" /></button>
      : <img className="calc-crop" src={source.crop} alt="Source region" loading="lazy" />)}
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

const MAIN_STEPS = 12

/** The technical view of "How we know": every step with its numbers, inputs and sources, the per-element table, checks, margin and confidence. */
export function CalculationPanel({ reasoning, title, onClose, onFocus, docTitle }: {
  reasoning: Reasoning; title?: string; onClose: () => void; onFocus?: (target: FocusTarget) => void; docTitle?: (id: string) => string
}) {
  // Engine output is data-driven and may omit any part: fill the gaps so every section simply disappears when empty.
  const claims = reasoning.calc?.kind === 'claims' ? reasoning.calc : undefined
  const numeric = reasoning.calc?.kind !== 'claims' ? reasoning.calc : undefined
  const calc: Calculation | undefined = numeric && { ...numeric, steps: (numeric.steps ?? []).map((s) => ({ ...s, inputs: s.inputs ?? [] })), rows: numeric.rows ?? [], checks: numeric.checks ?? [] }
  const method = reasoning.calc?.method
  const [width, setWidth] = useState(440)
  const [expanded, setExpanded] = useState(false)
  const drag = useRef<{ x: number; w: number } | null>(null)
  const clamp = (w: number) => Math.min(900, Math.max(300, w))
  const startDrag = (e: PointerEvent<HTMLDivElement>) => { drag.current = { x: e.clientX, w: width }; e.currentTarget.setPointerCapture(e.pointerId) }
  const moveDrag = (e: PointerEvent<HTMLDivElement>) => { if (drag.current) setWidth(clamp(drag.current.w + drag.current.x - e.clientX)) }
  const keyResize = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'ArrowLeft') { e.preventDefault(); setWidth((w) => clamp(w + 24)) }
    if (e.key === 'ArrowRight') { e.preventDefault(); setWidth((w) => clamp(w - 24)) }
  }
  const focus = onFocus && ((target: FocusTarget) => { setExpanded(false); onFocus(target) })
  const { confidence } = reasoning
  const margin = calc?.margin ?? reasoning.margin
  const result = calc?.result
  return <aside className={`viewer-calc-panel${expanded ? ' is-expanded' : ''}`} aria-label="Calculation" data-testid="calc-panel" style={expanded ? undefined : { width }}>
    {!expanded && <div className="calc-resize" role="separator" aria-orientation="vertical" aria-label="Resize calculation panel" aria-valuemin={300} aria-valuemax={900} aria-valuenow={width} tabIndex={0}
      onPointerDown={startDrag} onPointerMove={moveDrag} onPointerUp={(e) => { drag.current = null; e.currentTarget.releasePointerCapture(e.pointerId) }} onKeyDown={keyResize} />}
    <header>
      <Button className="calc-back" variant="ghost" size="sm" onClick={onClose}><ArrowLeft size={14} aria-hidden="true" />Drawing</Button>
      <div><strong>Calculation</strong>{title && <small>{title}</small>}</div>
      <Button className="calc-expand" variant="ghost" size="icon" aria-label={expanded ? 'Show the drawing beside it' : 'Expand calculation to full width'} aria-pressed={expanded} onClick={() => setExpanded(!expanded)}>{expanded ? <Minimize2 size={16} /> : <Maximize2 size={16} />}</Button>
      <Button variant="ghost" size="icon" aria-label="Close calculation" onClick={onClose}><X size={16} /></Button>
    </header>
    <div className="calc-content">
      {calc?.formula && <div className="calc-formula" data-testid="calc-formula">
        <code>{calc.formula}</code>
        {result && typeof result.value === 'number' && <p className="calc-result"><span>=</span> <b>{withUnit(result.value, result.unit)}</b>{result.rounded_as && <small>rounded to {result.rounded_as}</small>}</p>}
        {result && typeof result.value !== 'number' && <p className="calc-result">{Object.entries(result.value).map(([k, v]) => <span key={k}><b>{fmt(v)}</b> <small>{k}</small> </span>)}</p>}
      </div>}
      {method && <div className="calc-method" data-testid="calc-method">
        <p><strong>Method:</strong> {method.label}{method.why_chosen && <>, chosen because {method.why_chosen.replace(/^because\s+/i, '').replace(/\.$/, '')}.</>}</p>
        {!!method.alternatives?.length && <details className="calc-inputs calc-alternatives"><summary>Other methods considered ({method.alternatives.length})</summary>
          <table aria-label="Other methods considered"><thead><tr><th scope="col">Method</th><th scope="col" className="num">Value</th><th scope="col">Why not used</th></tr></thead>
            <tbody>{method.alternatives.map((alt, i) => <tr key={i}><th scope="row">{alt.label ?? alt.id}</th><td className="num">{alt.value == null ? '-' : typeof alt.value === 'number' ? withUnit(alt.value, alt.unit ?? '') : alt.value}</td><td>{alt.rejected_because}</td></tr>)}</tbody></table>
        </details>}
      </div>}
      {calc?.status === 'incomplete' && <p className="calc-warning" role="status">This calculation could not be reproduced in full.{calc.issues?.length ? ` ${calc.issues.join(' ')}` : ''}</p>}
      {!reasoning.calc && (reasoning.steps?.length
        ? <Section id="reasoning-steps" title="Steps"><ol className="calc-steps">{reasoning.steps.map((step, i) => <li key={i}><div className="calc-step-head"><span className="calc-index">{i + 1}</span><strong>{step.title}</strong></div><p className="calc-note">{step.text}</p></li>)}</ol></Section>
        : <p className="calc-none">No calculation was recorded for this answer. The steps are listed on the card.</p>)}

      {claims && <>
        <Section id="claims" title="Claims" hint={`${claims.result.claims_total}`}>
          <ol className="calc-steps calc-claims">{(claims.steps ?? []).filter((step) => step.section === 'claim' && step.level !== 'detail').map((step, i) => <li key={step.id ?? i}>
            <div className="calc-step-head"><span className="calc-index">{i + 1}</span><strong>{step.label}</strong></div>
            {step.status && <span className={`calc-claim-status is-${step.status}`}>{step.status === 'read_only' ? 'Read only' : step.status === 'verified' ? 'Verified' : 'Inferred'}</span>}
            {step.check && <p className="calc-note calc-claim-check">{step.check}</p>}
            <div className="calc-claim-sources">{(step.inputs ?? []).map((input, k) => <SourceLink key={k} source={input.source} docTitle={docTitle} onFocus={focus && ((target) => focus({ ...target, cite: step.cite }))} />)}</div>
          </li>)}</ol>
        </Section>
        {!!claims.steps?.some((step) => step.level === 'detail') && <Section id="claim-details" title="Details" open={false}>
          <ol className="calc-steps">{claims.steps.filter((step) => step.level === 'detail').map((step, i) => <li key={step.id ?? i} data-section={step.section}>
            <strong>{step.label}</strong>
            {step.value != null && <p className="calc-note">{typeof step.value === 'object' ? JSON.stringify(step.value) : withUnit(step.value, step.unit)}</p>}
            {!!step.inputs?.length && <ul className="calc-detail-inputs">{step.inputs.map((input, k) => <li key={k}>{input.name && <strong>{input.name}: </strong>}{input.value != null && <span>{withUnit(input.value, input.unit)} </span>}<SourceLink source={input.source} docTitle={docTitle} onFocus={focus} /></li>)}</ul>}
          </li>)}</ol>
        </Section>}
        {!!claims.checks?.length && <Section id="claim-checks" title="Checks">
          <ul className="calc-claim-checks">{claims.checks.map((check, i) => <li key={i}>{check.method}{check.value != null && <>: {fmt(check.value)}</>}{check.agrees != null && <> <span className={`calc-tag ${check.agrees ? 'is-ok' : 'is-off'}`}>{check.agrees ? 'agrees' : 'differs'}</span></>}</li>)}</ul>
        </Section>}
      </>}

      {!!reasoning.graph_path?.length && <Section id="path" title="Chain of evidence">
        <ol className="calc-path" aria-label="Chain of evidence">{reasoning.graph_path.map((node, i) => <li key={i}>
          {i > 0 && <span className="calc-edge" aria-hidden="true">→{node.relation ? ` ${node.relation}` : ''}</span>}
          {node.item_id && focus ? <button type="button" className="calc-node" onClick={() => focus({ item_id: node.item_id!, ...(node.doc_id ? { doc_id: node.doc_id } : {}), ...(node.page != null ? { page: node.page } : {}) })}>{node.label}</button> : <span className="calc-node">{node.label}</span>}
          {node.kind && <small>{node.kind}</small>}
        </li>)}</ol>
      </Section>}

      {!!calc?.steps.length && <Section id="steps" title="Steps" hint={`${calc.steps.length}`}>
        {(() => {
          const all = calc.steps
          // Engine marks supporting figures level="detail"; until it does, the first few steps lead and the rest fold away.
          const leveled = all.some((x) => x.level)
          const isMain = (x: (typeof all)[number], i: number) => leveled ? x.level !== 'detail' : i < MAIN_STEPS
          const main = all.map((x, i) => ({ x, i })).filter(({ x, i }) => isMain(x, i))
          const rest = all.map((x, i) => ({ x, i })).filter(({ x, i }) => !isMain(x, i))
          const item = ({ x: step, i }: { x: (typeof all)[number]; i: number }) => <li key={step.id} data-step={step.id} value={i + 1}>
            <div className="calc-step-head"><span className="calc-index">{i + 1}</span><strong>{step.label}</strong></div>
            <p className="calc-expr"><code>{step.expr}</code>{step.value != null && <span className="calc-eqline"><span className="calc-eq">=</span> <b className="calc-value">{withUnit(step.value, step.unit)}</b></span>}</p>
            {step.note && <p className="calc-note">{step.note}</p>}
            {!!step.inputs.length && <details className="calc-inputs"><summary>Inputs ({step.inputs.length})</summary>
              <table aria-label={`Inputs of ${step.label}`}><thead><tr><th scope="col">Input</th><th scope="col" className="num">Value</th><th scope="col">Source</th></tr></thead>
                <tbody>{step.inputs.map((input, k) => <tr key={k}><th scope="row">{input.name}</th><td className="num">{withUnit(input.value, input.unit)}</td><td><SourceLink source={input.source} docTitle={docTitle} onFocus={focus} /></td></tr>)}</tbody></table>
            </details>}
          </li>
          return <>
            <ol className="calc-steps">{main.map(item)}</ol>
            {!!rest.length && <details className="calc-more-steps" data-testid="calc-more-steps"><summary>Show all {all.length} steps ({rest.length} more)</summary>
              <ol className="calc-steps">{rest.map(item)}</ol>
            </details>}
          </>
        })()}
      </Section>}

      {!!calc?.rows.length && <Section id="rows" title="Per-element figures" hint={`${calc.rows.length}`}><RowsTable calc={calc} onFocus={focus} docTitle={docTitle} /></Section>}

      {!!calc?.scale_proof?.length && <Section id="scale" title="Scale proof" hint={`${calc.scale_proof.length}`} open={false}>
        {calc.scale_proof.map((proof, i) => <div key={i} className="calc-proof">
          <p className="calc-note"><b>{proof.method ?? 'scale'}</b>{proof.m_per_px != null && <> {fmt(proof.m_per_px, 6)} m/px</>}{proof.page != null && <>, page {proof.page}</>}{proof.spread_pct != null && <>, readings differ by up to {fmt(proof.spread_pct, 2)}%</>}</p>
          {proof.proof_warning && <p className="calc-warning" role="status">{proof.proof_warning}</p>}
          {!!proof.available_candidates?.length && <table aria-label="Scale readings"><thead><tr><th scope="col">Reading</th><th scope="col" className="num">m/px</th><th scope="col">Formula</th></tr></thead>
            <tbody>{proof.available_candidates.map((c, k) => <tr key={k}><th scope="row">{c.method}{c.note && <small>{c.note}</small>}</th><td className="num">{c.m_per_px != null ? fmt(c.m_per_px, 6) : '-'}</td><td><code>{c.formula}</code></td></tr>)}</tbody></table>}
        </div>)}
      </Section>}

      {!!calc?.inventory_rows?.length && <Section id="inventory" title="Everything saved on the sheet" hint={`${calc.inventory_rows.length}`} open={false}>
        <table aria-label="Saved inventory"><thead><tr><th scope="col">Item</th><th scope="col">Origin</th><th scope="col" className="num">Score</th></tr></thead>
          <tbody>{calc.inventory_rows.map((r, i) => <tr key={r.item_id ?? i} className={r.values?.alternative ? 'is-alt' : undefined}>
            <th scope="row">{r.label ?? r.values?.kind as string}{!!r.values?.alternative && <small>alternative extraction, not counted</small>}</th>
            <td>{String(r.values?.origin ?? '-')}</td><td className="num">{typeof r.values?.score === 'number' ? fmt(r.values.score, 2) : '-'}</td></tr>)}</tbody></table>
      </Section>}

      {calc?.reader && <Section id="reader" title="Second reader" open={false}>
        <p className="calc-note">{calc.reader.calculations?.length ?? 0} calculations, {calc.reader.tool_calls?.length ?? 0} tool calls{calc.reader.model_confidence != null && <>, self-reported confidence {fmt(calc.reader.model_confidence, 2)}</>}.</p>
        {calc.reader.note && <p className="calc-note">{calc.reader.note}</p>}
      </Section>}

      {!!calc?.unavailable?.length && <Section id="unavailable" title="Not available" hint={`${calc.unavailable.length}`}>
        <ul className="calc-unavailable">{calc.unavailable.map((u, i) => <li key={i} className="calc-note">{u}</li>)}</ul>
      </Section>}

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
        {margin.why && <p className="calc-note">{margin.why}</p>}
        {!!margin.sources?.length && <p className="calc-note">Based on: {(margin.sources ?? []).join('; ')}</p>}
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
