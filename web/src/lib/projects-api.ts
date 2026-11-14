import { apiFetch } from './api'

export const projectRoles = ['model', 'plan', 'section', 'elevation', 'detail', 'schedule', 'scan', 'photo', 'spec', 'revision', 'other'] as const
export type ProjectRole = typeof projectRoles[number]
export type ProjectDoc = { doc_id: string; title: string; kind: string; formats: string[]; role: ProjectRole; level: string | null; role_source: 'auto' | 'user'; thumb_url?: string; status?: string }
export type Project = { id: string; name: string; demo: boolean; created_at: string; docs: ProjectDoc[] }
export type ProjectSummary = Omit<Project, 'docs'> & { doc_count: number; updated_at?: string }
export type ProjectMistake = { id: string; severity: 'high' | 'medium' | 'low'; title: string; text: string; doc_ids: string[]; item_ids: string[]; evidence: { kind: string; values: Record<string, unknown> }; check: string }
export type ProjectOverview = {
  project_id: string
  totals: { storeys: number | null; rooms: number | null; doors: number | null; windows: number | null; floor_area_m2: number | null }
  levels: { level: string; rooms: number | null; doors: number | null; windows: number | null; floor_area_m2: number | null; sources: string[] }[]
  agreements: { what: string; values: { doc_id: string; value: unknown }[]; status: 'matches' | 'differs'; item_ids_by_doc: Record<string, string[]> }[]
  mistakes: ProjectMistake[]
  coverage: { doc_id: string; role: string; level: string | null; contributes: string; confidence_label: string }[]
}
export type ProjectChat = { id: string; title: string | null; created_at: string; project_id?: string | null }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(`/api${path}`, init)
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(typeof body?.detail === 'string' ? body.detail : `Could not load projects (${response.status}). Please try again.`)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}
const json = (method: string, body: unknown): RequestInit => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
const path = (id: string) => `/projects/${encodeURIComponent(id)}`
const realApi = {
  list: async () => (await request<{ projects: ProjectSummary[] }>('/projects')).projects,
  get: (id: string) => request<Project>(path(id)),
  create: (name: string, docIds: string[] = []) => request<Project>('/projects', json('POST', { name, doc_ids: docIds })),
  rename: (id: string, name: string) => request<Project>(path(id), json('PATCH', { name })),
  remove: (id: string) => request<void>(path(id), { method: 'DELETE' }),
  addDocs: (id: string, docIds: string[]) => request<Project>(`${path(id)}/docs`, json('POST', { doc_ids: docIds })),
  updateDoc: (id: string, docId: string, update: { role?: ProjectRole; level?: string | null }) => request<Project>(`${path(id)}/docs/${encodeURIComponent(docId)}`, json('PATCH', update)),
  removeDoc: (id: string, docId: string) => request<Project>(`${path(id)}/docs/${encodeURIComponent(docId)}`, { method: 'DELETE' }),
  upload: (id: string, file: File) => { const body = new FormData(); body.append('file', file); return request<{ doc_id: string; project: Project }>(`${path(id)}/upload`, { method: 'POST', body }) },
  overview: (id: string) => request<ProjectOverview>(`${path(id)}/overview`),
  chats: async (id: string) => (await request<{ chats: ProjectChat[] }>('/chats')).chats.filter((chat) => chat.project_id === id),
}
// Explicit opt-in only. An unavailable server never silently becomes sample data.
// This adapter starts empty; all content comes from what the user adds.
function mockApi(): typeof realApi {
  const read = (): Project[] => JSON.parse(localStorage.getItem('stoa-projects-generated-for-demo') || '[]')
  const write = (rows: Project[]) => localStorage.setItem('stoa-projects-generated-for-demo', JSON.stringify(rows))
  const get = async (id: string) => { const project = read().find((row) => row.id === id); if (!project) throw new Error('Project not found.'); return project }
  const update = async (id: string, mutate: (project: Project) => void) => { const rows = read(); const project = rows.find((row) => row.id === id); if (!project) throw new Error('Project not found.'); mutate(project); write(rows); return project }
  return {
    list: async () => read().map(({ docs, ...row }) => ({ ...row, doc_count: docs.length })), get,
    create: async (name, ids = []) => { const row: Project = { id: crypto.randomUUID(), name, demo: true, created_at: new Date().toISOString(), docs: [] }; write([...read(), row]); if (ids.length) return api.addDocs(row.id, ids); return row },
    rename: (id, name) => update(id, (row) => { row.name = name }),
    remove: async (id) => { write(read().filter((row) => row.id !== id)) },
    addDocs: async (id, ids) => { const { workspaceApi } = await import('./api'); const docs = await workspaceApi.getDocuments(); return update(id, (row) => { for (const doc of docs.filter((doc) => ids.includes(doc.doc_id))) if (!row.docs.some((old) => old.doc_id === doc.doc_id)) row.docs.push({ ...doc, role: 'other', level: null, role_source: 'auto' }) }) },
    updateDoc: (id, docId, value) => update(id, (row) => { const doc = row.docs.find((doc) => doc.doc_id === docId); if (doc) Object.assign(doc, value, { role_source: 'user' }) }),
    removeDoc: (id, docId) => update(id, (row) => { row.docs = row.docs.filter((doc) => doc.doc_id !== docId) }),
    upload: async () => { throw new Error('Uploads need a connected workspace. This screen is generated for demo.') },
    overview: async (id) => ({ project_id: id, totals: { storeys: null, rooms: null, doors: null, windows: null, floor_area_m2: null }, levels: [], agreements: [], mistakes: [], coverage: [] }),
    chats: async () => [],
  }
  // Resolved lazily after the adapter has been constructed.
}
export const projectsMock = import.meta.env.VITE_PROJECTS_MOCK === 'true'
const api = projectsMock ? mockApi() : realApi
export const projectsApi = api
export const projectHref = (id: string, tab?: string) => `#/projects?id=${encodeURIComponent(id)}${tab ? `&tab=${tab}` : ''}`
/** Chat inside a project. A question is sent as soon as the chat opens. */
export const projectChatHref = (id: string, chatId?: string, question?: string) => `#/chat?${new URLSearchParams({ ...(chatId ? { chat: chatId } : {}), ...(question ? { question, send: '1' } : {}), project: id })}`
/** Files chosen in New project, uploaded by the project page once it opens. */
const queued = new Map<string, File[]>()
export const queueUploads = (id: string, files: File[]) => { if (files.length) queued.set(id, files) }
export const takeUploads = (id: string) => { const files = queued.get(id) ?? []; queued.delete(id); return files }
