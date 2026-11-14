import { useEffect, useState } from 'react'
import { ArrowRight, BarChart3, RotateCw } from 'lucide-react'
import { Button } from './ui'
import {
  accuracyMatrix, comparisonRuns, dashboardApi, finite, formatDelta, formatLatency,
  formatNumber, formatPercent, formatUsd, questionsScored, runLabel, runTag,
  type BenchResult, type BenchRun, type CostsResult,
} from '../lib/dashboard'
import './accuracy-screen.css'

function Metric({ label, value, testId }: { label: string; value: string; testId?: string }) {
  return <div className="accuracy-metric"><dt>{label}</dt><dd data-testid={testId}>{value}</dd></div>
}

function RunNotice({ fake }: { fake?: boolean | null }) {
  if (fake === false) return null
  return <p className="accuracy-run-notice">{fake === true ? 'test run, fake model — these results do not measure real model performance.' : 'Model mode unknown: this run does not say whether it used a fake model.'}</p>
}

function AccuracyTable({ bench }: { bench: BenchResult }) {
  const matrix = accuracyMatrix(bench.data.cells)
  return <section className="accuracy-card" aria-labelledby="accuracy-breakdown-title">
    <header><h3 id="accuracy-breakdown-title">Accuracy by source and question type</h3><p>Text answers are not machine scored. Missing cells have no result.</p></header>
    {matrix.sources.length ? <div className="accuracy-table-scroll" role="region" aria-label="Accuracy table" tabIndex={0}>
      <table><caption className="accuracy-sr-only">Accuracy for each source and question type</caption><thead><tr><th scope="col">Source</th>{matrix.types.map((type) => <th key={type} scope="col">{type}</th>)}</tr></thead>
        <tbody>{matrix.sources.map((source) => <tr key={source}><th scope="row">{source}</th>{matrix.types.map((type) => {
          const cell = matrix.rows.get(source)?.get(type)
          const scored = questionsScored(cell)
          return <td key={type}>{cell ? <><strong>{formatPercent(cell.accuracy)}</strong>{finite(scored) && <small>{formatNumber(scored)} scored</small>}{finite(cell.unscored) && cell.unscored > 0 && <small>{formatNumber(cell.unscored)} not scored</small>}</> : <span aria-label="No result">—</span>}</td>
        })}</tr>)}</tbody>
      </table>
    </div> : <p className="accuracy-card-empty">No source breakdown in this run.</p>}
  </section>
}

function FineTuneComparison({ runs, bench }: { runs: BenchRun[]; bench: BenchResult }) {
  const pair = comparisonRuns(runs, bench)
  const beforeTag = pair?.[0].tag
  const afterTag = pair?.[1].tag
  const [results, setResults] = useState<[BenchResult, BenchResult] | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    setResults(null)
    setError('')
    if (beforeTag && afterTag) {
      Promise.all([dashboardApi.getBench(beforeTag, controller.signal), dashboardApi.getBench(afterTag, controller.signal)])
        .then(([before, after]) => {
          if (controller.signal.aborted) return
          if (!before || !after) throw new Error('A comparison run is no longer available.')
          if (before.data.set !== after.data.set || before.data.fake !== after.data.fake) throw new Error('These runs use different sets or model modes.')
          setResults([before, after])
        }).catch((err: Error) => { if (!controller.signal.aborted) setError(err.message) })
    }
    return () => controller.abort()
  }, [beforeTag, afterTag])
  const current = results && runTag(results[0]) === beforeTag && runTag(results[1]) === afterTag ? results : null
  const keys = current ? [...new Set([...Object.keys(current[0].data.cells || {}), ...Object.keys(current[1].data.cells || {})])]
    .filter((key) => key === 'ALL x ALL' || (!key.startsWith('ALL x ') && !key.endsWith(' x ALL'))).sort((a, b) => a === 'ALL x ALL' ? -1 : b === 'ALL x ALL' ? 1 : a.localeCompare(b)) : []
  return <section className="accuracy-card" aria-labelledby="accuracy-finetune-title">
    <header><h3 id="accuracy-finetune-title">Before / after fine-tuning</h3><p>Same question set and model mode. Delta is in percentage points.</p></header>
    {!pair ? <p className="accuracy-card-empty">No fine-tuned run yet.</p> : error ? <p className="accuracy-card-empty" role="alert">{error}</p> : !current ? <p className="accuracy-card-empty" role="status">Loading comparison…</p> : <>
      <RunNotice fake={current[0].data.fake} />
      {keys.length ? <div className="accuracy-table-scroll" role="region" aria-label="Fine-tuning comparison" tabIndex={0}><table>
        <caption className="accuracy-sr-only">Before and after accuracy on {current[0].data.set}</caption>
        <thead><tr><th scope="col">Source × type</th><th scope="col">Baseline<small>{runLabel({ tag: runTag(current[0]), fake: current[0].data.fake ?? null })}</small></th><th scope="col">Fine-tuned<small>{runLabel({ tag: runTag(current[1]), fake: current[1].data.fake ?? null })}</small></th><th scope="col">Delta</th></tr></thead>
        <tbody>{keys.map((key) => {
          const before = current[0].data.cells?.[key]
          const after = current[1].data.cells?.[key]
          return <tr key={key}><th scope="row">{key === 'ALL x ALL' ? 'Overall' : key}</th><td>{before ? formatPercent(before.accuracy) : 'No result'}</td><td>{after ? formatPercent(after.accuracy) : 'No result'}</td><td>{before && after ? formatDelta(before.accuracy, after.accuracy) : 'No result'}</td></tr>
        })}</tbody>
      </table></div> : <p className="accuracy-card-empty">No scored breakdown in these runs.</p>}
    </>}
  </section>
}

export function AccuracyScreen() {
  const [runs, setRuns] = useState<BenchRun[]>([])
  const [tag, setTag] = useState('')
  const [bench, setBench] = useState<BenchResult | null>(null)
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
  const total = bench?.data.cells?.['ALL x ALL']
  const providers = costs ? Object.entries(costs.by_provider).sort((a, b) => b[1].usd - a[1].usd || a[0].localeCompare(b[0])) : []

  return <section className="accuracy-screen" aria-label="Accuracy dashboard">
    <header className="accuracy-header"><div><h2><BarChart3 size={19} />Accuracy</h2><p>Bench results and model spend from the workspace.</p></div>
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
        <Metric label="Accuracy" value={formatPercent(total?.accuracy)} testId="bench-accuracy" />
        <Metric label="Answered accuracy" value={formatPercent(total?.answered_accuracy)} testId="bench-answered-accuracy" />
        <Metric label="Questions scored" value={formatNumber(questionsScored(total))} testId="bench-scored" />
        <Metric label="Cost per answer" value={formatUsd(total?.cost_usd_per_answer)} testId="bench-cost-per-answer" />
        <Metric label="Mean latency" value={formatLatency(total?.latency_ms_mean)} testId="bench-latency" />
      </dl>
      <p className="accuracy-method">Accuracy includes abstentions and errors. Answered accuracy counts correct and wrong answers only. Text answers are not scored.</p>
      <AccuracyTable bench={bench} />
      <FineTuneComparison key={`${selectedTag}-${refresh}`} runs={options} bench={bench} />
    </>}
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
