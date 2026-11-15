import { mkdirSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, test, type Page, type Route } from '@playwright/test'
import type { Project, ProjectOverview } from '../src/lib/projects-api'
import { mockCluster, mockGraph, mockNode } from '../src/lib/kg-mock'

// Projects UI against fixtures served from the page (the backend is built in parallel).
// Set PROJ_SHOTS=<dir> to write the review screenshots.
const shots = process.env.PROJ_SHOTS
if (shots) mkdirSync(resolve(shots), { recursive: true })
const shoot = async (page: Page, name: string) => { if (shots) await page.screenshot({ path: resolve(shots, `${name}.png`), fullPage: false }) }

const library = [
  { doc_id: 'ac20_arc', source: 'demo', formats: ['ifc'], kind: 'ifc', title: 'ac20_arc', pages: 1, licence: 'x', credit: 'x', heldout: false },
  { doc_id: 'plan-l1', source: 'demo', formats: ['png'], kind: 'raster', title: 'Level 1 plan', pages: 1, licence: 'x', credit: 'x', heldout: false },
  { doc_id: 'plan-l2', source: 'demo', formats: ['dxf'], kind: 'dxf', title: 'Level 2 plan', pages: 1, licence: 'x', credit: 'x', heldout: false },
  { doc_id: 'spec-a', source: 'demo', formats: ['pdf'], kind: 'pdf', title: 'Door schedule', pages: 3, licence: 'x', credit: 'x', heldout: false },
]
const doc = (id: string, title: string, kind: string, format: string, role: Project['docs'][number]['role'], level: string | null, role_source: 'auto' | 'user' = 'auto') =>
  ({ doc_id: id, title, kind, formats: [format], role, level, role_source })
const baseProject = (): Project => ({
  id: 'p1', name: 'Harbour Street 12', demo: false, created_at: new Date(Date.now() - 3 * 86400_000).toISOString(),
  docs: [doc('ac20_arc', 'ac20_arc', 'ifc', 'ifc', 'model', null), doc('plan-l1', 'Level 1 plan', 'raster', 'png', 'plan', 'Level 1'), doc('plan-l2', 'Level 2 plan', 'dxf', 'dxf', 'plan', 'Level 2', 'user'), doc('spec-a', 'Door schedule', 'pdf', 'pdf', 'schedule', null)],
})
const overview: ProjectOverview = {
  project_id: 'p1', totals: { storeys: 2, rooms: 14, doors: 22, windows: 19, floor_area_m2: 212.4 },
  levels: [{ level: 'Level 1', rooms: 8, doors: 12, windows: 11, floor_area_m2: 118.2, sources: ['ac20_arc', 'plan-l1'] }, { level: 'Level 2', rooms: 6, doors: 10, windows: 8, floor_area_m2: 94.2, sources: ['plan-l2'] }],
  agreements: [{ what: 'Doors on Level 1', values: [{ doc_id: 'ac20_arc', value: 12 }, { doc_id: 'plan-l1', value: 12 }], status: 'matches', item_ids_by_doc: {} },
    { what: 'Windows on Level 1', values: [{ doc_id: 'ac20_arc', value: 11 }, { doc_id: 'plan-l1', value: 10 }], status: 'differs', item_ids_by_doc: {} }],
  mistakes: [{ id: 'm1', severity: 'high', title: 'Window count differs on Level 1', text: 'The model shows 11 windows, the plan shows 10.', doc_ids: ['plan-l1'], item_ids: ['w-1'], evidence: { kind: 'count', values: {} }, check: 'the north wall of the living room' }],
  coverage: [{ doc_id: 'ac20_arc', role: 'model', level: null, contributes: 'rooms, doors, windows, areas', confidence_label: 'Exact' }, { doc_id: 'plan-l1', role: 'plan', level: 'Level 1', contributes: 'doors, windows', confidence_label: 'Read from drawing' }],
}
const thumb = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120"><rect width="120" height="120" fill="#fafaf8"/><path d="M14 14h92v92H14zM14 60h50M64 14v46M64 80h42" fill="none" stroke="#9a9a92" stroke-width="2"/></svg>`

async function backend(page: Page, state: { projects: Project[]; fail?: boolean; slow?: boolean; chats?: unknown[] }) {
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
  await page.route(/\/api\//, async (route) => {
    const url = new URL(route.request().url()), method = route.request().method(), path = url.pathname
    if (path === '/api/docs') return json(route, { sources: [{ docs: library }] })
    const one = path.match(/^\/api\/docs\/([^/]+)$/)
    if (one) return json(route, library.find((l) => l.doc_id === one[1]))
    if (/\/planmap\/\d+$/.test(path)) return json(route, { doc_id: 'plan-l1', page: 1, items: [{ item_id: 'w-1', bbox_px: [30, 30, 60, 50], tag: 'W1' }] })
    if (/\/files\/[^/]+\.png$/.test(path)) return route.fulfill({ contentType: 'image/svg+xml', body: thumb })
    if (/thumb\.png$/.test(path)) return route.fulfill({ contentType: 'image/svg+xml', body: thumb })
    if (path === '/api/chats' && method === 'GET') return json(route, { chats: state.chats ?? [] })
    if (!path.startsWith('/api/projects')) return route.fallback()
    if (state.slow) await new Promise((done) => setTimeout(done, 1200))
    if (state.fail) return json(route, { detail: 'The server is not reachable right now.' }, 503)
    const rest = path.replace('/api/projects', '').split('/').filter(Boolean)
    if (!rest.length) {
      if (method === 'POST') { const body = route.request().postDataJSON() as { name: string; doc_ids?: string[] }; const created: Project = { id: `p${state.projects.length + 1}`, name: body.name, demo: false, created_at: new Date().toISOString(), docs: (body.doc_ids ?? []).map((id) => doc(id, library.find((l) => l.doc_id === id)!.title, 'raster', 'png', 'plan', null)) }; state.projects.push(created); return json(route, created) }
      return json(route, { projects: state.projects.map(({ docs, ...row }) => ({ ...row, doc_count: docs.length })) })
    }
    const project = state.projects.find((row) => row.id === rest[0])
    if (!project) return json(route, { detail: 'Project not found.' }, 404)
    if (rest[1] === 'overview') return json(route, overview)
    if (rest[1] === 'graph') {
      const full = mockGraph(project.id)
      if (rest[2] === 'node') return json(route, mockNode(full, decodeURIComponent(rest[3])))
      if (rest[2] === 'stats') return json(route, full.stats)
      return json(route, url.searchParams.get('depth') === 'full' ? full : mockCluster(full))
    }
    if (rest[1] === 'docs' && method === 'POST') { for (const id of (route.request().postDataJSON() as { doc_ids: string[] }).doc_ids) project.docs.push(doc(id, library.find((l) => l.doc_id === id)!.title, 'raster', 'png', 'other', null)); return json(route, project) }
    if (rest[1] === 'docs' && method === 'PATCH') { Object.assign(project.docs.find((d) => d.doc_id === rest[2])!, route.request().postDataJSON(), { role_source: 'user' }); return json(route, project) }
    if (rest[1] === 'docs' && method === 'DELETE') { project.docs = project.docs.filter((d) => d.doc_id !== rest[2]); return json(route, project) }
    if (rest[1] === 'upload') { project.docs.push(doc('uploaded-1', 'New upload', 'raster', 'png', 'plan', null)); return json(route, { doc_id: 'uploaded-1', project }) }
    if (method === 'PATCH') { project.name = (route.request().postDataJSON() as { name: string }).name; return json(route, project) }
    if (method === 'DELETE') { state.projects = state.projects.filter((row) => row !== project); return route.fulfill({ status: 204 }) }
    return json(route, project)
  })
}

test.describe('desktop', () => {
  test.use({ viewport: { width: 1400, height: 1000 } })

  test('list: empty state, then New project creates and opens it', async ({ page }) => {
    const state = { projects: [] as Project[] }
    await backend(page, state)
    await page.goto('/#/projects')
    await expect(page.getByRole('heading', { name: 'Projects', level: 1 }).first()).toBeVisible()
    await expect(page.getByText(/No projects yet/i)).toBeVisible()
    await shoot(page, 'list-empty')
    await page.getByRole('button', { name: 'New project' }).first().click()
    const dialog = page.getByRole('dialog', { name: 'New project' })
    await dialog.getByLabel('Name').fill('Harbour Street 12')
    await dialog.getByRole('button', { name: /Add from library/ }).click()
    await dialog.getByRole('option', { name: /Level 1 plan/ }).click()
    await shoot(page, 'new-project')
    await dialog.getByRole('button', { name: /^Create/ }).click()
    await expect(page.getByRole('heading', { name: 'Harbour Street 12', level: 1 })).toBeVisible()
    expect(state.projects).toHaveLength(1)
  })

  test('list: cards, search and loading', async ({ page }) => {
    const state = { projects: [baseProject(), { ...baseProject(), id: 'p2', name: 'Sample school', docs: [] }], slow: true }
    await backend(page, state)
    await page.goto('/#/projects')
    await expect(page.getByLabel('Loading projects')).toBeVisible()
    await shoot(page, 'list-loading')
    await expect(page.getByRole('link', { name: /Harbour Street 12/ })).toBeVisible()
    await shoot(page, 'list')
    await page.getByRole('searchbox').fill('school')
    await expect(page.getByRole('link', { name: /Harbour Street 12/ })).toHaveCount(0)
  })

  test('list: an unreachable server shows a plain error with Try again', async ({ page }) => {
    await backend(page, { projects: [], fail: true })
    await page.goto('/#/projects')
    await expect(page.getByRole('alert')).toContainText('not reachable')
    await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible()
    await shoot(page, 'list-error')
  })

  test('project page: ask, files with role and level, overview, Show opens the viewer', async ({ page }) => {
    test.setTimeout(45_000)
    const state = { projects: [baseProject()], chats: [{ id: 'c1', title: 'How many doors?', created_at: new Date(Date.now() - 3600_000).toISOString(), project_id: 'p1' }] }
    await backend(page, state)
    await page.goto('/#/projects?id=p1')
    await expect(page.getByRole('heading', { name: 'Harbour Street 12', level: 1 })).toBeVisible()
    await expect(page.locator('.pj-head').getByText(/4 files/)).toBeVisible()
    await expect(page.getByRole('link', { name: /How many doors/ })).toBeVisible()
    await shoot(page, 'project-chats')
    await page.getByRole('tab', { name: 'Files' }).click()
    await expect(page.getByText('Set by you')).toBeVisible()
    await expect(page.getByRole('navigation', { name: 'Document folders' })).toContainText('Plans')
    await page.getByRole('button', { name: 'Open Plans folder' }).click()
    await expect(page.locator('.pj-explorer .data-file-row')).toHaveCount(2)
    await page.getByRole('button', { name: 'Open All Files folder' }).click()
    const edit = async (id: string, type: string, level: string) => {
      await page.locator(`.pj-explorer [data-doc-id="${id}"]`).getByLabel(/^Actions for/).click()
      await page.getByRole('button', { name: 'Change type and level' }).click()
      const dialog = page.getByRole('dialog', { name: 'Type and level' })
      await dialog.getByLabel('Type').selectOption(type)
      await dialog.getByLabel('Level').fill(level)
      await dialog.getByRole('button', { name: 'Save' }).click()
    }
    await edit('ac20_arc', 'model', 'Level 1')
    await expect.poll(() => state.projects[0].docs[0].level).toBe('Level 1')
    await edit('spec-a', 'spec', '')
    await expect.poll(() => state.projects[0].docs[3].role).toBe('spec')
    await page.getByRole('button', { name: 'Open Level 1 plan' }).click()
    await expect(page.locator('.pj-explorer').getByRole('complementary', { name: 'Document details' })).toBeVisible()
    await shoot(page, 'project-files')
    await page.getByRole('button', { name: 'Close document details' }).click()
    await page.getByLabel('Actions for Door schedule').click()
    await page.getByRole('button', { name: 'Remove Door schedule from project' }).click()
    await expect(page.locator('.pj-explorer [data-doc-id="spec-a"]')).toHaveCount(0)
    await page.getByRole('tab', { name: 'Overview' }).click()
    await expect(page.getByText('212 m²')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Mistakes found' })).toBeVisible()
    await expect(page.getByText('Window count differs on Level 1')).toBeVisible()
    await shoot(page, 'project-overview')
    await page.getByRole('button', { name: 'Show' }).click()
    await expect(page.getByRole('dialog', { name: 'Viewer' })).toBeVisible({ timeout: 10_000 })
    await page.waitForTimeout(900)
    await shoot(page, 'viewer-from-mistake')
  })

  test('project page: empty project and Add files dialog', async ({ page }) => {
    await backend(page, { projects: [{ ...baseProject(), docs: [] }] })
    await page.goto('/#/projects?id=p1&tab=files')
    await expect(page.getByTestId('files-empty')).toContainText('Add plans, models, scans or PDFs for this building')
    await shoot(page, 'project-empty')
    await page.getByTestId('files-empty').getByRole('button', { name: 'Add files' }).click()
    await expect(page.getByRole('dialog', { name: 'Add files' })).toBeVisible()
    await shoot(page, 'add-files')
  })

  test('chat in a project: breadcrumb, content panel, picker limited to the project', async ({ page }) => {
    const project = baseProject(); project.docs = project.docs.slice(0, 2)
    await backend(page, { projects: [project] })
    await page.goto('/#/chat?project=p1')
    await expect(page.getByRole('navigation', { name: 'Breadcrumb' })).toContainText('Harbour Street 12')
    const panel = page.getByRole('complementary', { name: 'Project content' })
    await expect(panel.getByRole('button', { name: /Open Level 1 plan/ })).toBeVisible()
    await expect(panel.getByRole('button', { name: /Open Level 2 plan/ })).toHaveCount(0)
    await page.locator('#question').fill('How many @')
    const options = page.getByRole('listbox')
    await expect(options.getByText('Level 1 plan')).toBeVisible()
    await expect(options.getByText('Door schedule')).toHaveCount(0)
    await page.locator('#question').fill('')
    await shoot(page, 'chat-in-project')
  })
})

test.describe('phone', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true })
  const noScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)

  for (const [name, hash] of [['list', '#/projects'], ['project', '#/projects?id=p1'], ['files', '#/projects?id=p1&tab=files'], ['overview', '#/projects?id=p1&tab=overview'], ['chat', '#/chat?project=p1']] as const) {
    test(`phone ${name}: no horizontal scroll`, async ({ page }) => {
      await backend(page, { projects: [baseProject()] })
      await page.goto(`/${hash}`)
      await page.waitForTimeout(900)
      expect(await noScroll(page)).toBe(true)
      await shoot(page, `phone-${name}`)
    })
  }
})

test('graph tab: stats, search, details with plain-words methods, check these list', async ({ page }) => {
  await backend(page, { projects: [baseProject()] })
  await page.goto('/#/projects?id=p1&tab=graph')
  await expect(page.getByTestId('graph-tab')).toBeVisible()
  await expect(page.getByLabel('Graph totals')).toContainText('Items')
  await page.getByRole('searchbox', { name: 'Search the graph' }).fill('kitchen')
  await page.getByRole('listbox').getByRole('button').first().click()
  const panel = page.getByRole('complementary', { name: 'Item details' })
  await expect(panel).toContainText('Kitchen')
  await expect(panel.getByText(/matched by position/).first()).toBeVisible()
  await expect(panel.getByRole('button', { name: 'Ask about this' })).toBeVisible()
  await panel.getByRole('button', { name: 'Ask about this' }).click()
  await expect(page.locator('#project-question')).toHaveValue(/Kitchen/)
  await page.locator('button.kg-check').click()
  await expect(page.getByRole('complementary', { name: 'Check these' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})
