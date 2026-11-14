import { useEffect, useState } from 'react'
import { ArrowRight, BarChart3, RotateCw } from 'lucide-react'
import { Button } from './ui'
import {
  dashboardApi, finite, formatDelta, formatLatency, formatNumber, formatPercent,
  formatUsd, questionsScored, runLabel, runTag,
  type BenchCell, type BenchResult, type BenchRun, type CostsResult,
} from '../lib/dashboard'
import './accuracy-screen.css'

interface AccuracyCell extends BenchCell {
  abstained?: number
  error?: number
  latency_ms_p95?: number | null
}
interface TextCell {
  n?: number
  correct?: number
  partial?: number
  wrong?: number
  abstained?: number
  unjudged?: number
  accuracy?: number | null
  score?: number | null
  judge_usd?: number
}
type AccuracyBench = BenchResult & { data: {
  cells?: Record<string, AccuracyCell>
  text?: Record<string, TextCell>
} }

/** Use the server's marginal totals, never average percentages or percentiles. */
export function deriveAccuracyTables(cells: Record<string, AccuracyCell> = {}) {
  const sources: { label: string; cell: AccuracyCell }[] = []
  const types: { label: string; cell: AccuracyCell }[] = []
  for (const [key, cell] of Object.entries(cells)) {
    const separator = key.lastIndexOf(' x ')
    if (separator < 0) continue
    const source = key.slice(0, separator)
    const type = key.slice(separator + 3)
    if (!source || !type) continue
    if (source !== 'ALL' && type === 'ALL') sources.push({ label: source, cell })
    if (source === 'ALL' && type !== 'ALL') types.push({ label: type, cell })
  }
  const alphabetical = (a: { label: string }, b: { label: string }) => a.label.localeCompare(b.label)
  return { total: cells['ALL x ALL'], sources: sources.sort(alphabetical), types: types.sort(alphabetical) }
}

function Metric({ label, value, testId }: { label: string; value: string; testId?: string }) {
  return <div className="accuracy-metric"><dt>{label}</dt><dd data-testid={testId}>{value}</dd></div>
}

function RunNotice({ fake }: { fake?: boolean | null }) {
  if (fake === false) return null
  return <p className="accuracy-run-notice">{fake === true ? 'test run, fake model — these results do not measure real model performance.' : 'Model mode unknown: this run does not say whether it used a fake model.'}</p>
}

export function AccuracyTable({ title, rows }: { title: string; rows: { label: string; cell: AccuracyCell }[] }) {
  return <section className="accuracy-card" aria-label={title}>
    <header><h3>{title}</h3><p>n includes all questions. Accuracy excludes unscored text; abstentions and errors count as incorrect.</p></header>
    {rows.length ? <div className="accuracy-table-scroll" role="region" aria-label={`${title} table`} tabIndex={0}>
      <table><caption className="accuracy-sr-only">{title}</caption><thead><tr>
        <th scope="col">{title === 'Per source' ? 'Source' : 'Question type'}</th><th scope="col">n</th><th scope="col">Correct</th><th scope="col">Accuracy</th><th scope="col">Answered accuracy</th><th scope="col">$/answer</th><th scope="col">p95 latency</th>
      </tr></thead><tbody>{rows.map(({ label, cell }) => <tr key={label}>
        <th scope="row">{label}</th><td>{formatNumber(cell.n)}</td><td>{formatNumber(cell.correct)}</td><td>{formatPercent(cell.accuracy)}</td><td>{formatPercent(cell.answered_accuracy)}</td><td>{formatUsd(cell.cost_usd_per_answer)}</td><td>{formatLatency(cell.latency_ms_p95)}</td>
      </tr>)}</tbody></table>
    </div> : <p className="accuracy-card-empty">No breakdown reported in this run.</p>}
  </section>
}

function TextJudge({ text }: { text?: Record<string, TextCell> }) {
  const rows = Object.entries(text || {}).sort(([a], [b]) => a === 'ALL' ? -1 : b === 'ALL' ? 1 : a.localeCompare(b))
  return <section className="accuracy-card" aria-labelledby="accuracy-text-title">
    <header><h3 id="accuracy-text-title">Text judge</h3><p>Reported separately from numeric accuracy. Accuracy = correct ÷ (correct + partial + wrong). Weighted score gives partial answers half credit. Abstained and unjudged answers are excluded.</p></header>
    {rows.length ? <div className="accuracy-table-scroll" role="region" aria-label="Text judge results" tabIndex={0}><table>
      <caption className="accuracy-sr-only">Text judge results by source</caption><thead><tr>{['Source', 'n', 'Correct', 'Partial', 'Wrong', 'Abstained', 'Unjudged', 'Accuracy', 'Weighted score', 'Judge cost'].map((label) => <th key={label} scope="col">{label}</th>)}</tr></thead>
      <tbody>{rows.map(([source, cell]) => <tr key={source}><th scope="row">{source === 'ALL' ? 'Overall' : source}</th><td>{formatNumber(cell.n)}</td><td>{formatNumber(cell.correct)}</td><td>{formatNumber(cell.partial)}</td><td>{formatNumber(cell.wrong)}</td><td>{formatNumber(cell.abstained)}</td><td>{formatNumber(cell.unjudged)}</td><td>{formatPercent(cell.accuracy)}</td><td>{formatPercent(cell.score)}</td><td>{formatUsd(cell.judge_usd)}</td></tr>)}</tbody>
    </table></div> : <p className="accuracy-card-empty">No text-judge results reported in this run.</p>}
  </section>
}

function RunPicker({ label, value, runs, onChange }: { label: string; value: string; runs: BenchRun[]; onChange: (tag: string) => void }) {
  return <label>{label}<select aria-label={label} value={value} disabled={!runs.length} onChange={(event) => onChange(event.target.value)}>
    {!value && <option value="">Choose a run</option>}
    {runs.map((run) => <option key={run.tag} value={run.tag}>{runLabel(run)}</option>)}
  </select></label>
}

function RunComparison({ runs, bench }: { runs: BenchRun[]; bench: AccuracyBench }) {
  const currentTag = runTag(bench)
  const [tagA, setTagA] = useState(() => runs.find((run) => run.tag !== currentTag && run.set === bench.data.set && run.fake === bench.data.fake)?.tag || '')
  const [tagB, setTagB] = useState(currentTag)
  const [results, setResults] = useState<[AccuracyBench, AccuracyBench] | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    setResults(null)
    setError('')
    if (tagA && tagB && tagA !== tagB) {
      Promise.all([dashboardApi.getBench(tagA, controller.signal), dashboardApi.getBench(tagB, controller.signal)])
        .then(([before, after]) => {
          if (controller.signal.aborted) return
          if (!before || !after) throw new Error('A comparison run is no longer available.')
          if (!before.data.set || before.data.set !== after.data.set || typeof before.data.fake !== 'boolean' || before.data.fake !== after.data.fake) throw new Error('Choose runs with the same question set and known model mode.')
          if (before.data.totals?.stopped_by_max_usd || after.data.totals?.stopped_by_max_usd || before.data.totals?.questions !== after.data.totals?.questions) throw new Error('These runs have different completion counts or stopped at the cost limit. Choose complete runs with matching question counts.')
          setResults([before, after])
        }).catch((err: Error) => { if (!controller.signal.aborted) setError(err.message) })
    }
    return () => controller.abort()
  }, [tagA, tagB])
  const current = results && runTag(results[0]) === tagA && runTag(results[1]) === tagB ? results : null
  const left = deriveAccuracyTables(current?.[0].data.cells)
  const right = deriveAccuracyTables(current?.[1].data.cells)
  const rows = current ? [
    { label: 'Overall numeric', before: left.total?.accuracy, after: right.total?.accuracy },
    { label: 'Text judge', before: current[0].data.text?.ALL?.accuracy, after: current[1].data.text?.ALL?.accuracy },
    ...(['sources', 'types'] as const).flatMap((group) => [...new Set([...left[group], ...right[group]].map((row) => row.label))].sort().map((label) => ({
      label: `${group === 'sources' ? 'Source' : 'Type'} · ${label}`,
      before: left[group].find((row) => row.label === label)?.cell.accuracy,
      after: right[group].find((row) => row.label === label)?.cell.accuracy,
    }))),
  ] : []
  return <section className="accuracy-card" aria-labelledby="accuracy-comparison-title">
    <header><h3 id="accuracy-comparison-title">Before / after comparison</h3><p>Choose tag A (before) and tag B (after). Delta is B − A in percentage points. Matching set names and counts do not guarantee identical questions; verify run provenance.</p></header>
    <div className="accuracy-controls accuracy-comparison-controls"><RunPicker label="Tag A · before" value={tagA} runs={runs} onChange={setTagA} /><RunPicker label="Tag B · after" value={tagB} runs={runs} onChange={setTagB} /></div>
    {!tagA || !tagB || tagA === tagB ? <p className="accuracy-card-empty">Choose two different tags to compare.</p> : error ? <p className="accuracy-card-empty" role="alert">{error}</p> : !current ? <p className="accuracy-card-empty" role="status">Loading comparison…</p> : <>
      <RunNotice fake={current[0].data.fake} />
      <div className="accuracy-table-scroll" role="region" aria-label="Before and after results" tabIndex={0}><table>
        <caption className="accuracy-sr-only">Accuracy comparison for {tagA} and {tagB}</caption><thead><tr><th scope="col">Measure</th><th scope="col">Before<small>{tagA}</small></th><th scope="col">After<small>{tagB}</small></th><th scope="col">Delta</th></tr></thead>
        <tbody>{rows.map(({ label, before, after }) => <tr key={label}><th scope="row">{label}</th><td>{formatPercent(before)}</td><td>{formatPercent(after)}</td><td>{formatDelta(before, after)}</td></tr>)}</tbody>
      </table></div>
    </>}
  </section>
}

export function AccuracyScreen() {
  const [runs, setRuns] = useState<BenchRun[]>([])
  const [tag, setTag] = useState('')
  const [bench, setBench] = useState<AccuracyBench | null>(null)
  const [costs, setCosts] = useState<CostsResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [costsLoading, setCostsLoading] = useState(true)
  const [benchError, setBenchError] = useState('')
  const [runsError, setRunsError] = useState('')
  const [costsError, setCostsError] = useState('')
  const [refresh, setRefresh] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setRunsError('')
    dashboardApi.getRuns(controller.signal).then((data) => { if (!controller.signal.aborted) setRuns(data) })
      .catch((err: Error) => { if (!controller.signal.aborted) setRunsError(err.message) })
    setCostsLoading(true)
    setCostsError('')
    setCosts(null)
    dashboardApi.getCosts(controller.signal).then((data) => { if (!controller.signal.aborted) setCosts(data) })
      .catch((err: Error) => { if (!controller.signal.aborted) setCostsError(err.message) })
      .finally(() => { if (!controller.signal.aborted) setCostsLoading(false) })
    return () => controller.abort()
  }, [refresh])

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setBench(null)
    setBenchError('')
    dashboardApi.getBench(tag || undefined, controller.signal).then((data) => { if (!controller.signal.aborted) setBench(data) })
      .catch((err: Error) => { if (!controller.signal.aborted) setBenchError(err.message) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [tag, refresh])

  const selectedTag = tag || (bench ? runTag(bench) : '')
  const options = [...runs]
  if (bench && !options.some((run) => run.tag === runTag(bench))) options.unshift({ tag: runTag(bench), set: bench.data.set ?? null, fake: bench.data.fake ?? null })
  const tables = deriveAccuracyTables(bench?.data.cells)
  const total = tables.total
  const providers = costs ? Object.entries(costs.by_provider).sort((a, b) => b[1].usd - a[1].usd || a[0].localeCompare(b[0])) : []

  return <section className="accuracy-screen" aria-label="Accuracy dashboard">
    <header className="accuracy-header"><div><h2><BarChart3 size={19} />Accuracy</h2><p>Measured results from held-out drawing questions.</p></div>
      <div className="accuracy-controls"><label>Run<select aria-label="Bench run" value={selectedTag} disabled={!options.length} onChange={(event) => setTag(event.target.value)}>
        {!selectedTag && <option value="">{loading ? 'Loading latest run…' : 'No bench runs'}</option>}
        {selectedTag && !options.some((run) => run.tag === selectedTag) && <option value={selectedTag}>{selectedTag}</option>}
        {options.map((run) => <option key={run.tag} value={run.tag}>{runLabel(run)}</option>)}
      </select></label><Button variant="raised" aria-label="Refresh dashboard" onClick={() => setRefresh((value) => value + 1)}><RotateCw size={15} /><span>Refresh</span></Button></div>
    </header>
    {runsError && <p className="accuracy-message" role="alert">{runsError} Showing the selected result where available.</p>}
    {loading ? <p className="accuracy-message" role="status">Loading bench results…</p> : benchError ? <p className="accuracy-message" role="alert">{benchError}</p> : !bench ? <div className="accuracy-empty" role="status"><h3>No bench run yet.</h3><p>Run <code>python -m engine.bench --set sample200 --tag &lt;t&gt;</code>.</p></div> : <>
      <div className="accuracy-run-meta"><span>Question set: <strong>{bench.data.set || 'Not available'}</strong></span><span>{bench.file}</span></div>
      <RunNotice fake={bench.data.fake} />
      {bench.data.totals?.stopped_by_max_usd && <p className="accuracy-message">Partial run: stopped at the cost limit. {formatNumber(bench.data.totals.questions)} of {formatNumber(bench.data.totals.of)} questions completed.</p>}
      <dl className="accuracy-metrics" aria-label="Bench totals">
        <Metric label="Numeric accuracy" value={formatPercent(total?.accuracy)} testId="bench-accuracy" />
        <Metric label="Abstentions · numeric" value={formatNumber(total?.abstained)} testId="bench-abstentions" />
        <Metric label="Cost per answer" value={formatUsd(total?.cost_usd_per_answer)} testId="bench-cost-per-answer" />
        <Metric label="Answered accuracy" value={formatPercent(total?.answered_accuracy)} testId="bench-answered-accuracy" />
        <Metric label="Questions scored" value={formatNumber(questionsScored(total))} testId="bench-scored" />
        <Metric label="Mean latency" value={formatLatency(total?.latency_ms_mean)} testId="bench-latency" />
      </dl>
      <p className="accuracy-method">Numeric accuracy includes abstentions and errors. Answered accuracy counts correct and wrong numeric answers only. Cost per answer covers answering all questions, excluding the text judge’s cost below.</p>
      <AccuracyTable title="Per source" rows={tables.sources} />
      <AccuracyTable title="Per question type" rows={tables.types} />
      <TextJudge text={bench.data.text} />
      <RunComparison key={`${selectedTag}-${refresh}-${runs.map((run) => run.tag).join('|')}`} runs={options} bench={bench} />
    </>}
    <section className="accuracy-card accuracy-measurement" aria-labelledby="accuracy-measurement-title"><header><h3 id="accuracy-measurement-title">How we measure</h3></header>
      <p>Held-out drawings are never used for training or tuning. Counts must match exactly; area, length and volume allow a 2% tolerance or 0.05 absolute units, whichever is larger.</p>
      <p>Text answers are judged separately by a model against the dataset’s gold answer and question: correct means the same facts, partial means some facts match, and wrong means contradictory or unrelated facts. The judge can err; unjudged answers stay unscored. A statement that data is missing can be judged correct when it matches the gold answer.</p>
      <p>Missing metrics are shown as unavailable or not scored. Fake-model runs are labelled and do not measure real model performance.</p>
    </section>
    <div className="accuracy-bottom-grid">
      <section className="accuracy-card" aria-labelledby="accuracy-costs-title"><header><h3 id="accuracy-costs-title">Model costs</h3><p>All logged calls, across runs and workspace questions.</p></header>
        {costsLoading ? <p className="accuracy-card-empty" role="status">Loading model costs…</p> : costsError ? <p className="accuracy-card-empty" role="alert">{costsError}</p> : costs && <>
          <dl className="accuracy-cost-total"><Metric label="Total spend" value={formatUsd(costs.total_usd)} testId="costs-total" /><Metric label="Model calls" value={formatNumber(costs.calls)} /></dl>
          {providers.length ? <div className="accuracy-table-scroll"><table aria-label="Costs by provider"><thead><tr><th scope="col">Provider</th><th scope="col">Calls</th><th scope="col">Spend</th></tr></thead><tbody>{providers.map(([provider, value]) => <tr key={provider}><th scope="row">{provider}</th><td>{formatNumber(value.calls)}</td><td>{formatUsd(value.usd)}</td></tr>)}</tbody></table></div> : <p className="accuracy-card-empty">No model calls logged yet.</p>}
        </>}
      </section>
      <section className="accuracy-card" aria-labelledby="accuracy-models-title"><header><h3 id="accuracy-models-title">Model switcher</h3><p>Read-only route order</p></header>
        <ol className="accuracy-routes" aria-label="Model routes"><li>Rules</li><li><ArrowRight size={14} aria-hidden="true" />Nemotron</li><li><ArrowRight size={14} aria-hidden="true" />Runware</li></ol>
        <p className="accuracy-card-empty">switching from the UI comes with S-09</p>
      </section>
    </div>
  </section>
}

// In-source Vitest tests keep W-24 within the two-file scope. Enable includeSource
// for this file in a temporary Vitest config to run them; production drops this block.
declare global { interface ImportMeta { vitest?: typeof import('vitest') } }
if (import.meta.env.MODE === 'test' && import.meta.vitest) {
  const { describe, it, expect } = import.meta.vitest
  describe('accuracy table derivation', () => {
    it('uses marginal totals without mixing intersections or averaging metrics', () => {
      const source = { n: 10, correct: 7, accuracy: 0.7, answered_accuracy: 0.875, cost_usd_per_answer: 0.002, latency_ms_p95: 95, abstained: 2 }
      const type = { n: 4, correct: 3, accuracy: 0.75, latency_ms_p95: 200 }
      const total = { n: 14, correct: 10, accuracy: 10 / 14 }
      const result = deriveAccuracyTables({ 'ALL x ALL': total, 'z-source x ALL': source, 'ALL x count': type, 'z-source x count': { n: 999, accuracy: 1, latency_ms_p95: 999 }, 'a-source x ALL': { n: 0, correct: 0, accuracy: null }, malformed: { n: 999 } })
      expect(result.total).toBe(total)
      expect(result.sources.map((row) => row.label)).toEqual(['a-source', 'z-source'])
      expect(result.sources[1].cell).toBe(source)
      expect(result.types).toEqual([{ label: 'count', cell: type }])
      expect(result.sources[0].cell.accuracy).toBeNull()
    })
    it('preserves real zeroes and missing values, without inventing aggregates', () => {
      expect(deriveAccuracyTables()).toEqual({ total: undefined, sources: [], types: [] })
      expect(deriveAccuracyTables({ 'source x count': { n: 2, correct: 1 } }).sources).toEqual([])
      const result = deriveAccuracyTables({ 'ALL x text': { n: 5, accuracy: null }, 'source x ALL': { n: 0, abstained: 0, cost_usd_per_answer: 0 } })
      expect(result.sources[0].cell.abstained).toBe(0)
      expect(result.sources[0].cell.cost_usd_per_answer).toBe(0)
      expect(result.sources[0].cell.latency_ms_p95).toBeUndefined()
      expect(result.types[0].cell.accuracy).toBeNull()
      expect(finite(result.types[0].cell.accuracy)).toBe(false)
    })
  })
}
