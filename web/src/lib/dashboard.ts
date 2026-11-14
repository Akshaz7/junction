export interface BenchRun {
  tag: string
  set: string | null
  fake: boolean | null
  mtime?: string | number
}

export interface BenchCell {
  n?: number
  scored?: number
  correct?: number
  unscored?: number
  accuracy?: number | null
  answered_accuracy?: number | null
  cost_usd_per_answer?: number | null
  latency_ms_mean?: number | null
}

export interface BenchResult {
  file: string
  data: {
    tag?: string
    set?: string | null
    fake?: boolean | null
    totals?: { questions?: number; of?: number; stopped_by_max_usd?: boolean }
    cells?: Record<string, BenchCell>
  }
}

export interface CostsResult {
  total_usd: number
  calls: number
  by_provider: Record<string, { calls: number; usd: number }>
  by_task: Record<string, { calls: number; usd: number }>
}

/** Dashboard reads always use the real API; there is no offline number fallback. */
export class DashboardApi {
  constructor(private transport: typeof fetch = (...args) => fetch(...args)) {}

  private async request(path: string, signal?: AbortSignal) {
    const response = await this.transport(path, { signal })
    const body: unknown = await response.json().catch(() => null)
    return { response, body }
  }

  async getRuns(signal?: AbortSignal): Promise<BenchRun[]> {
    const { response, body } = await this.request('/api/bench', signal)
    // Older servers expose only /bench/latest; that result can still be shown.
    if (response.status === 404) return []
    if (!response.ok) throw new Error(`Could not load bench runs (${response.status}).`)
    const rows = Array.isArray(body) ? body : (body as { benches?: unknown } | null)?.benches
    if (!Array.isArray(rows)) throw new Error('The bench run list is unavailable.')
    return rows as BenchRun[]
  }

  async getBench(tag?: string, signal?: AbortSignal): Promise<BenchResult | null> {
    const path = `/api/bench/latest${tag ? `?tag=${encodeURIComponent(tag)}` : ''}`
    const { response, body } = await this.request(path, signal)
    if (response.status === 404 && (body as { status?: string } | null)?.status === 'no_bench') return null
    if (!response.ok) throw new Error(`Could not load the bench result (${response.status}).`)
    if (!body || typeof body !== 'object' || !('data' in body) || !body.data || typeof body.data !== 'object') {
      throw new Error('The bench result is unavailable.')
    }
    return body as BenchResult
  }

  async getCosts(signal?: AbortSignal): Promise<CostsResult> {
    const { response, body } = await this.request('/api/costs', signal)
    if (!response.ok) throw new Error(`Could not load model costs (${response.status}).`)
    if (!body || typeof body !== 'object' || !('by_provider' in body) || !body.by_provider) {
      throw new Error('Model costs are unavailable.')
    }
    return body as CostsResult
  }
}

export const dashboardApi = new DashboardApi()

export const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)
export const formatPercent = (value: unknown) => finite(value) ? `${(value * 100).toFixed(1)}%` : 'not scored'
export const formatUsd = (value: unknown) => finite(value) ? `$${value.toFixed(Math.abs(value) < 0.01 ? 6 : 2)}` : 'Not available'
export const formatNumber = (value: unknown) => finite(value) ? value.toLocaleString('en-US') : 'Not available'
export const formatLatency = (value: unknown) => finite(value) ? `${formatNumber(value)} ms` : 'Not available'
export function formatDelta(before: unknown, after: unknown) {
  if (!finite(before) || !finite(after)) return 'not scored'
  const delta = Number(((after - before) * 100).toFixed(1))
  return `${delta > 0 ? '+' : ''}${delta.toFixed(1)} pp`
}

export function runTag(bench: BenchResult) {
  return bench.data.tag || bench.file.replace(/\.json$/, '')
}

export function runLabel(run: Pick<BenchRun, 'tag' | 'fake'>) {
  return `${run.tag}${run.fake === true ? ' · test run, fake model' : run.fake == null ? ' · model mode unknown' : ''}`
}

export function questionsScored(cell?: BenchCell) {
  if (finite(cell?.scored)) return cell.scored
  if (finite(cell?.n) && finite(cell?.unscored)) return cell.n - cell.unscored
  return undefined
}

export function accuracyMatrix(cells: Record<string, BenchCell> = {}) {
  const sources = new Set<string>()
  const types = new Set<string>()
  const rows = new Map<string, Map<string, BenchCell>>()
  for (const [key, cell] of Object.entries(cells)) {
    const separator = key.lastIndexOf(' x ')
    if (separator < 0) continue
    const source = key.slice(0, separator)
    const type = key.slice(separator + 3)
    if (!source || !type || source === 'ALL' || type === 'ALL') continue
    sources.add(source)
    types.add(type)
    if (!rows.has(source)) rows.set(source, new Map())
    rows.get(source)!.set(type, cell)
  }
  return { sources: [...sources].sort(), types: [...types].sort(), rows }
}

/** Compare the same set and model mode, preferring the selected run when possible. */
export function comparisonRuns(runs: BenchRun[], selected: BenchResult): [BenchRun, BenchRun] | null {
  if (!selected.data.set || typeof selected.data.fake !== 'boolean') return null
  const eligible = runs.filter((run) => run.set === selected.data.set && run.fake === selected.data.fake)
  const newestFirst = (a: BenchRun, b: BenchRun) => {
    if (a.tag === runTag(selected)) return -1
    if (b.tag === runTag(selected)) return 1
    const timestamp = (run: BenchRun) => typeof run.mtime === 'number' ? run.mtime : Date.parse(run.mtime || '') || 0
    return timestamp(b) - timestamp(a)
  }
  const baseline = eligible.filter((run) => /baseline/i.test(run.tag)).sort(newestFirst)[0]
  const finetune = eligible.filter((run) => /fine[-_]?tun|(?:^|[-_.])ft(?:$|[-_.\d])/i.test(run.tag) && !/baseline/i.test(run.tag)).sort(newestFirst)[0]
  return baseline && finetune ? [baseline, finetune] : null
}
