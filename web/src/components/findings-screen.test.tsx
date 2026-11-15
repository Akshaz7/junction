// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FindingsScreen, runCoverage, runNotice, type FindingsRunResult } from './findings-screen'
import type { Document } from '../lib/types'
import type { Finding } from '../lib/findings'

vi.mock('./document-viewer', () => ({ useViewerSheet: () => ({}), DocumentViewer: () => null }))
vi.mock('../viewer3d/VisualiseIt', () => ({ VisualisePanel: () => null }))
vi.mock('../viewer3d/liveHighlight', () => ({ onFindingsUpdated: () => () => {}, onAdvisorCards: () => () => {} }))

const finding: Finding = { id: 'f1', doc_id: 'doc-one', rule_id: 'fi-fire-exits-per-storey', item_ids: ['door-1'], severity: 'violation', message: 'Only one exit', detail: {}, rule: { id: 'fi-fire-exits-per-storey', text: 'Two exits' } }
const run = (extra: Partial<FindingsRunResult>): FindingsRunResult => ({ status: 'ok', findings: [], ...extra })

describe('runNotice', () => {
  it('says which rules were checked, on how many items, and the outcome', () => {
    const text = runNotice(run({ findings: [finding], checked: ['fi-fire-exits-per-storey'], items_checked: 85, checked_at: '2026-11-15T08:00:00Z' }))
    expect(text).toMatch(/^Checked 1 rule on 85 items at .+: 1 finding\.$/)
  })
  it('never reports an all-clear when no rule was checked', () => {
    expect(runNotice(run({ checked: [], not_checked: [{ rule_id: 'a', reason: 'needs an IFC model' }] }))).toBe('No rule could be checked on this drawing, so no findings is not an all-clear.')
    expect(runNotice(run({ coverage: { checked: [], not_checked: [] } }))).not.toContain('no rule problems found')
    expect(runNotice(run({}))).toContain('not an all-clear')
  })
  it('counts rules that could not be checked next to a clean result', () => {
    expect(runNotice(run({ checked: ['a', 'b'], items_checked: 1, not_checked: [{ rule_id: 'c', reason: 'no stair data' }] }))).toBe('Checked 2 rules on 1 item: no rule problems found. 1 rule not checked (no usable input).')
    expect(runNotice(run({ coverage: { checked: ['a'], not_checked: [] } }))).toBe('Checked 1 rule: no rule problems found.')
  })
  it('shows the server reason for no_checks, waiting and not enough data', () => {
    expect(runNotice(run({ status: 'no_checks', detail: 'Rule checks need an IFC model.' }))).toBe('Rule checks need an IFC model.')
    expect(runNotice(run({ status: 'no_checks' }))).toBe('Checks are not available for this drawing yet.')
    expect(runNotice(run({ status: 'waiting' }))).toBe('Waiting for the drawing to finish processing')
    expect(runNotice(run({ status: 'not_enough_data', detail: 'Not enough readable data (0 of 12 items)' }))).toBe('Not enough readable data (0 of 12 items)')
  })
  it('keeps the plain completion line when the server gives no coverage', () => {
    expect(runNotice(run({ findings: [finding] }))).toBe('Checks complete.')
    expect(runCoverage(run({ findings: [finding] }))).toBeNull()
  })
})

describe('FindingsScreen run', () => {
  const docs: Document[] = [{ doc_id: 'doc-one', source: 'demo', formats: ['ifc'], kind: 'ifc', title: 'doc-one', pages: 1, licence: 'MIT', credit: '', heldout: false }]
  let host: HTMLDivElement, root: Root, response: unknown
  beforeEach(() => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input)
      if (path.startsWith('/api/findings?')) return Response.json({ findings: [] })
      if (path === '/api/findings/run') return Response.json(response)
      if (path === '/api/advise') return Response.json({ cards: [] })
      throw new Error(`Unexpected request: ${path}`)
    }))
    host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  })
  afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals() })
  async function runChecks() {
    await act(async () => root.render(<FindingsScreen docs={docs} />))
    const button = [...host.querySelectorAll('button')].find((b) => b.textContent === 'Run checks')!
    await act(async () => { button.click() })
  }

  it('lists the rules checked and not checked, with reasons', async () => {
    response = { status: 'ok', findings: [], checked: ['fi-fire-exits-per-storey'], items_checked: 85, not_checked: [{ rule_id: 'fi-stair-width', reason: 'no stair flight with a footprint in the model' }] }
    await runChecks()
    expect(host.querySelector('[role="status"]')?.textContent).toBe('Checked 1 rule on 85 items: no rule problems found. 1 rule not checked (no usable input).')
    const details = host.querySelector('[data-testid="findings-coverage"]')!
    expect(details.querySelector('[aria-label="Rules checked"] li')?.getAttribute('title')).toBe('fi-fire-exits-per-storey')
    expect(details.querySelector('[aria-label="Rules not checked"]')?.textContent).toContain('no stair flight with a footprint in the model')
  })
  it('shows the server reason, not an all-clear, when nothing could be checked', async () => {
    response = { status: 'no_checks', detail: 'Rule checks need an IFC model.', findings: [], checked: [], not_checked: [] }
    await runChecks()
    expect(host.querySelector('[role="status"]')?.textContent).toBe('Rule checks need an IFC model.')
    expect(host.textContent).not.toContain('no rule problems found')
  })
})
