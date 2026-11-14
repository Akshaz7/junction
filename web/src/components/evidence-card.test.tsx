// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { EvidenceCard } from './evidence-card'
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

const citation = { n: 1, doc_id: 'd', page: 1, kind: 'region' as const, bbox_px: null, item_ids: [], quote: null }
const answer = {
  citations: [citation],
  reasoning: {
    steps: [
      { kind: 'found', title: 'Found', text: 'Room Küche 2.02', cite: 1 },
      { kind: 'checked', title: 'Checked', text: 'Label agrees', ok: true },
    ],
    confidence: { label: 'Cross-checked', pct: 94, reason: 'Outline and label agree.', improve: null },
  },
} as unknown as Answer

it('renders steps and the confidence pill', async () => {
  await act(async () => root.render(<EvidenceCard answer={answer} onOpenCitation={vi.fn()} />))
  expect(host.querySelectorAll('li').length).toBe(2)
  expect(host.textContent).toContain('Room Küche 2.02')
  expect(host.querySelector('.evidence-pill')!.textContent).toBe('Cross-checked · 94%')
  expect(host.querySelector('.evidence-pill')!.getAttribute('aria-label')).toContain('94')
})

it('opens the matching citation when a step is clicked', async () => {
  const onOpen = vi.fn()
  await act(async () => root.render(<EvidenceCard answer={answer} onOpenCitation={onOpen} />))
  await act(async () => host.querySelector<HTMLButtonElement>('button.evidence-row')!.click())
  expect(onOpen).toHaveBeenCalledWith(citation)
  expect(host.querySelectorAll('button').length).toBe(1)
})

it('renders nothing without reasoning', async () => {
  await act(async () => root.render(<EvidenceCard answer={{ ...answer, reasoning: undefined }} onOpenCitation={vi.fn()} />))
  expect(host.innerHTML).toBe('')
})

it('shows the graph path and a link to the graph when the chat belongs to a project', async () => {
  window.location.hash = '#/chat?chat=c1&project=p9'
  const withPath = { ...answer, reasoning: { ...answer.reasoning!, graph_path: [{ from_label: 'Grille G1', edge_kind: 'serves', to_label: 'Room 2.02' }] } } as Answer
  await act(async () => root.render(<EvidenceCard answer={withPath} onOpenCitation={vi.fn()} />))
  expect(host.textContent).toContain('Grille G1')
  expect(host.textContent).toContain('Room 2.02')
  const link = host.querySelector('a')
  expect(link?.getAttribute('href')).toContain('tab=graph')
  expect(link?.getAttribute('href')).toContain('id=p9')
  window.location.hash = ''
})
