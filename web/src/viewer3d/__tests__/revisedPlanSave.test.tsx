// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

vi.mock('../../lib/api', () => ({
  workspaceApi: {
    getDocument: vi.fn(async () => ({ pages: 1 })),
    getPlanMap: vi.fn(async () => null),
    getPageImage: vi.fn(async () => new Blob()),
  },
}))
import { RevisedPlanDialog } from '../RevisedPlanDialog'

let root: Root, host: HTMLDivElement
beforeEach(() => { (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true; host = document.createElement('div'); document.body.append(host); root = createRoot(host) })
afterEach(() => { act(() => root.unmount()); host.remove() })

const button = () => [...host.querySelectorAll('button')].find((b) => /Save as new version|Saving/.test(b.textContent ?? ''))

it('Revised plan has "Save as new version" next to Download PNG, and shows the compare link after saving', async () => {
  const onSave = vi.fn()
  await act(async () => root.render(<RevisedPlanDialog docId="d" manifest={null} removed={['door-1']} moved={{}} onClose={() => {}}
    save={{ canSave: true, busy: false, onSave }} />))
  const save = button()!
  expect(save.previousElementSibling?.textContent).toBe('Download PNG')
  act(() => save.click())
  expect(onSave).toHaveBeenCalledOnce()

  await act(async () => root.render(<RevisedPlanDialog docId="d" manifest={null} removed={['door-1']} moved={{}} onClose={() => {}}
    save={{ canSave: true, busy: false, onSave, message: 'Saved as edited version 1.', href: '#/compare?change=dv:d:0-1' }} />))
  expect(host.querySelector('[role=status]')?.textContent).toContain('Saved as edited version 1.')
  expect(host.querySelector<HTMLAnchorElement>('a')?.getAttribute('href')).toBe('#/compare?change=dv:d:0-1')
})

it('is disabled with no edits and absent without a save control', async () => {
  await act(async () => root.render(<RevisedPlanDialog docId="d" manifest={null} removed={[]} moved={{}} onClose={() => {}}
    save={{ canSave: false, busy: false, onSave: () => {} }} />))
  expect(button()?.disabled).toBe(true)
  await act(async () => root.render(<RevisedPlanDialog docId="d" manifest={null} removed={[]} moved={{}} onClose={() => {}} />))
  expect(button()).toBeUndefined()
})
