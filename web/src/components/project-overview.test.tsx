// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { OverviewTab, summary, type OverviewState } from './project-overview'
import type { Project, ProjectOverview } from '../lib/projects-api'

let host: HTMLDivElement
let root: Root
beforeEach(() => { Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true }); host = document.createElement('div'); document.body.append(host); root = createRoot(host) })
afterEach(async () => { await act(async () => root.unmount()); host.remove() })

const project: Project = { id: 'p', name: 'P', demo: false, created_at: '', docs: [{ doc_id: 'a', title: 'Level 1 plan', kind: 'raster', formats: ['png'], role: 'plan', level: 'Level 1', role_source: 'auto' }] }
const data: ProjectOverview = {
  project_id: 'p', totals: { storeys: 1, rooms: 8, doors: 12, windows: null, floor_area_m2: 118.2 },
  levels: [{ level: 'Level 1', rooms: 8, doors: 12, windows: null, floor_area_m2: 118.2, sources: ['a'] }],
  agreements: [{ what: 'Doors', values: [{ doc_id: 'a', value: 12 }], status: 'differs', item_ids_by_doc: {} }],
  mistakes: [{ id: 'm', severity: 'high', title: 'Count differs', text: 'Model 11, plan 10.', doc_ids: ['a'], item_ids: ['i1'], evidence: { kind: 'count', values: {} }, check: 'the north wall' }],
  coverage: [],
}
const state = (extra: Partial<OverviewState>): OverviewState => ({ error: '', loading: false, retry: () => {}, ...extra })

it('summarises totals, agreement and mistakes in one line each', () => {
  expect(summary.totals(data)).toBe('1 storey, 8 rooms, 12 doors')
  expect(summary.agree(data)).toBe('0 agree, 1 differs')
  expect(summary.mistakes(data)).toBe('1 to check')
  expect(summary.mistakes({ ...data, mistakes: [] })).toBe('Nothing flagged')
})

it('shows each mistake with its check and a Show button that passes the cited items', async () => {
  const onShow = vi.fn()
  await act(async () => root.render(<OverviewTab project={project} overview={state({ data })} onShow={onShow} showBusy={null} />))
  expect(host.textContent).toContain('Mistakes found')
  expect(host.textContent).toContain('To check: the north wall')
  expect(host.textContent).toContain('Differs')
  await act(async () => [...host.querySelectorAll('button')].find((b) => b.textContent === 'Show')!.click())
  expect(onShow).toHaveBeenCalledWith('a', ['i1'])
})

it('says so when there is nothing to total, and shows a retry on error', async () => {
  const retry = vi.fn()
  await act(async () => root.render(<OverviewTab project={{ ...project, docs: [] }} overview={state({})} onShow={() => {}} showBusy={null} />))
  expect(host.textContent).toContain('Nothing to total yet')
  await act(async () => root.render(<OverviewTab project={project} overview={state({ error: 'The overview could not be loaded.', retry })} onShow={() => {}} showBusy={null} />))
  expect(host.textContent).toContain('The overview could not be loaded.')
  await act(async () => [...host.querySelectorAll('button')].find((b) => /try again/i.test(b.textContent ?? ''))!.click())
  expect(retry).toHaveBeenCalled()
})
