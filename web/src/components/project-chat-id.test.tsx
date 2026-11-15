// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../lib/projects-api', async (original) => ({ ...(await original<typeof import('../lib/projects-api')>()), projectsApi: api }))
import { useChatProject } from './project-chat-panel'

let host: HTMLDivElement, root: Root
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
})
afterEach(async () => { await act(async () => root.unmount()); host.remove() })

it('knows the project on the very render that opens the project chat, and never shows another project’s record', async () => {
  const renders: Array<{ id: string | null; project: string | null }> = []
  api.get.mockImplementation(async (id: string) => ({ id, name: `Project ${id}`, docs: [{ doc_id: `${id}-a` }, { doc_id: `${id}-b` }] }))
  function Probe({ active }: { active: boolean }) {
    const p = useChatProject(active)
    renders.push({ id: p.id, project: p.project?.id ?? null })
    return null
  }
  window.location.hash = '#/projects/p1'
  await act(async () => root.render(<Probe active={false} />))
  renders.length = 0
  // the project page links to the chat: address and view change together
  window.history.replaceState(null, '', '#/chat?project=p1&question=hi&send=1')
  await act(async () => root.render(<Probe active />))
  expect(renders[0].id).toBe('p1')            // not null: a null here made the auto-send look project-less
  expect(renders.at(-1)).toEqual({ id: 'p1', project: 'p1' })
  // switching project: the old record is not returned for the new id
  renders.length = 0
  window.history.replaceState(null, '', '#/chat?project=p2')
  await act(async () => { window.dispatchEvent(new HashChangeEvent('hashchange')) })
  expect(renders.every((r) => r.id === 'p2' ? r.project === null || r.project === 'p2' : true)).toBe(true)
  expect(renders.at(-1)).toEqual({ id: 'p2', project: 'p2' })
})
