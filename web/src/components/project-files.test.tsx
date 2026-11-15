// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { FilesTab } from './project-files'
import { ProjectContentPanel } from './project-chat-panel'
import { projectsApi, type Project } from '../lib/projects-api'

let host: HTMLDivElement
let root: Root
beforeEach(() => { Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true }); window.matchMedia = window.matchMedia ?? ((query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {} }) as unknown as MediaQueryList); host = document.createElement('div'); document.body.append(host); root = createRoot(host) })
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks() })

const project: Project = {
  id: 'p', name: 'Harbour Street 12', demo: false, created_at: '',
  docs: [
    { doc_id: 'a', title: 'Level 1 plan', kind: 'raster', formats: ['png'], role: 'plan', level: null, role_source: 'auto' },
    { doc_id: 'b', title: 'Level 2 plan', kind: 'dxf', formats: ['dxf'], role: 'plan', level: 'Level 2', role_source: 'user' },
  ],
}

const clickText = async (text: string, scope: ParentNode = document) => act(async () => [...scope.querySelectorAll('button')].find((b) => b.textContent?.trim() === text)!.click())

it('labels automatic and user-set roles and saves a changed type from the row menu', async () => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
  const update = vi.spyOn(projectsApi, 'updateDoc').mockResolvedValue(project)
  const onProject = vi.fn()
  await act(async () => root.render(<FilesTab project={project} pending={[]} onDismiss={() => {}} onProject={onProject} onAdd={() => {}} />))
  expect(host.textContent).not.toContain('Set automatically')
  expect(host.textContent).toContain('Set by you')
  expect(host.querySelector('select[aria-label^="Type of"]')).toBeNull()
  await clickText('Change type and level', host.querySelector('[data-doc-id="a"]')!)
  const select = document.querySelector<HTMLSelectElement>('dialog select[aria-label="Type"]')!
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!
    setter.call(select, 'section'); select.dispatchEvent(new Event('change', { bubbles: true }))
  })
  await clickText('Save')
  expect(update).toHaveBeenCalledWith('p', 'a', { role: 'section', level: null })
  expect(onProject).toHaveBeenCalledWith(project)
})

it('groups files into folders by type with counts and filters the list', async () => {
  const mixed: Project = { ...project, docs: [...project.docs, { doc_id: 'c', title: 'ac20_arc', kind: 'ifc', formats: ['ifc'], role: 'model', level: null, role_source: 'auto' }] }
  await act(async () => root.render(<FilesTab project={mixed} pending={[]} onDismiss={() => {}} onProject={() => {}} onAdd={() => {}} />))
  const folders = host.querySelector('nav[aria-label="Document folders"]')!
  expect(folders.textContent).toContain('All Files3')
  expect(folders.textContent).toContain('Models1')
  expect(folders.textContent).toContain('Plans2')
  await act(async () => folders.querySelector<HTMLButtonElement>('[aria-label="Open Models folder"]')!.click())
  expect(host.querySelectorAll('[data-doc-id]')).toHaveLength(1)
})

it('gives every file name a tooltip with the full name', async () => {
  await act(async () => root.render(<FilesTab project={project} pending={[]} onDismiss={() => {}} onProject={() => {}} onAdd={() => {}} />))
  expect(host.querySelector('[data-doc-id="a"] h3')!.getAttribute('title')).toBe('Level 1 plan')
})

it('removes a file from the project', async () => {
  const remove = vi.spyOn(projectsApi, 'removeDoc').mockResolvedValue({ ...project, docs: [project.docs[1]] })
  await act(async () => root.render(<FilesTab project={project} pending={[]} onDismiss={() => {}} onProject={() => {}} onAdd={() => {}} />))
  await act(async () => host.querySelector<HTMLButtonElement>('[aria-label="Remove Level 1 plan from project"]')!.click())
  expect(remove).toHaveBeenCalledWith('p', 'a')
})

it('shows the empty state and opens the add dialog from it', async () => {
  const onAdd = vi.fn()
  await act(async () => root.render(<FilesTab project={{ ...project, docs: [] }} pending={[]} onDismiss={() => {}} onProject={() => {}} onAdd={onAdd} />))
  expect(host.textContent).toContain('Add plans, models, scans or PDFs for this building')
  await act(async () => [...host.querySelectorAll('button')].find((b) => b.textContent?.includes('Add files'))!.click())
  expect(onAdd).toHaveBeenCalled()
})

it('shows a failed upload in plain words with Dismiss', async () => {
  const onDismiss = vi.fn()
  await act(async () => root.render(<FilesTab project={project} pending={[{ key: 'k', name: 'broken.ifc', error: 'This file is too large.' }]} onDismiss={onDismiss} onProject={() => {}} onAdd={() => {}} />))
  expect(host.textContent).toContain('This file is too large.')
  await act(async () => [...host.querySelectorAll('button')].find((b) => b.textContent === 'Dismiss')!.click())
  expect(onDismiss).toHaveBeenCalledWith('k')
})

it('lists the project files as tiles with type tags beside the chat', async () => {
  await act(async () => root.render(<ProjectContentPanel project={project} />))
  expect(host.querySelector('[aria-label="Project content"]')).not.toBeNull()
  expect(host.textContent).toContain('Harbour Street 12')
  expect(host.querySelectorAll('.pj-tile')).toHaveLength(2)
  expect(host.textContent).toContain('PNG')
  expect(host.textContent).toContain('DXF')
})
