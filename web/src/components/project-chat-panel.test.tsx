import { expect, it } from 'vitest'
import { projectLibraryDocs } from './project-chat-panel'
import type { Document } from '../lib/types'
import type { Project } from '../lib/projects-api'

const entry = (id: string, kind = 'ifc') => ({ doc_id: id, title: id, kind, formats: [kind], role: 'model', level: null, role_source: 'auto' }) as unknown as Project['docs'][number]
it('attaches every project file, including ones the library list does not have yet', () => {
  const library = [{ doc_id: 'a', title: 'A', kind: 'ifc', formats: ['ifc'], source: 'uploads', pages: 1, licence: '', credit: '', heldout: false }] as Document[]
  const project = { id: 'p', name: 'P', demo: false, created_at: '', docs: [entry('a'), entry('b'), entry('c')] } as Project
  expect(projectLibraryDocs(project, library).map((d) => d.doc_id)).toEqual(['a', 'b', 'c'])
  expect(projectLibraryDocs(project, library)[1].title).toBe('b')
  expect(projectLibraryDocs(project, [])).toHaveLength(3)
})
