import { test, expect, production, docs } from './final-helpers'

// Contract: handoff/F-PROJECTS-CONTRACT.md v1. Enable when both feature branches have commits.
test.setTimeout(180_000)
test.beforeEach(() => test.skip(process.env.E2E_PROJECTS !== '1', 'Projects branches are not integrated yet; enable E2E_PROJECTS=1 on the integrated stack'))

test('[PROJECTS] Project list and seeded demo open in the real browser', async ({ page, request }) => {
  const response = await request.get('/api/projects')
  expect(response.ok(), 'Contract GET /api/projects').toBe(true)
  const { projects } = await response.json()
  expect(Array.isArray(projects)).toBe(true)
  expect(projects.some((p: { demo: boolean }) => p.demo), 'At least one real demo project is seeded').toBe(true)
  await page.goto('/#/projects')
  const demo = projects.find((p: { demo: boolean }) => p.demo)
  await expect(page.getByText(demo.name, { exact: true }).first()).toBeVisible()
  await page.getByText(demo.name, { exact: true }).first().click()
  await expect(page).toHaveURL(new RegExp(demo.id))
  const detail = await request.get(`/api/projects/${demo.id}`)
  expect(detail.ok()).toBe(true)
  const project = await detail.json()
  expect(project.docs.length).toBeGreaterThan(0)
  await expect(page.getByText(project.docs[0].title, { exact: true }).first()).toBeVisible()
  await page.screenshot({ path: test.info().outputPath('demo-project.png') })
})

test('[PROJECTS] Create, attach, classify, edit metadata, overview, project chat, remove and delete', async ({ page, request }) => {
  test.skip(production, 'Production is read-only: project writes forbidden')
  const available = await docs(request)
  const kinds = new Set<string>()
  const chosen = available.filter((doc) => {
    if (kinds.has(doc.kind) || !['ifc', 'dxf', 'raster'].includes(doc.kind)) return false
    kinds.add(doc.kind); return true
  }).slice(0, 3)
  const name = `E2E project ${Date.now()}`
  const create = await request.post('/api/projects', { data: { name, doc_ids: [chosen[0].doc_id] } })
  expect(create.ok()).toBe(true)
  let project = await create.json()
  const id = project.id
  expect(project.name).toBe(name)
  try {
    const add = await request.post(`/api/projects/${id}/docs`, { data: { doc_ids: chosen.slice(1).map((d) => d.doc_id) } })
    expect(add.ok()).toBe(true)
    project = await add.json()
    expect(project.docs.map((d: { doc_id: string }) => d.doc_id).sort()).toEqual(chosen.map((d) => d.doc_id).sort())
    const roles = ['model', 'plan', 'section', 'elevation', 'detail', 'schedule', 'scan', 'photo', 'spec', 'revision', 'other']
    for (const doc of project.docs) {
      expect(roles).toContain(doc.role)
      expect(doc.role_source).toBe('auto')
    }
    const edit = await request.patch(`/api/projects/${id}/docs/${encodeURIComponent(chosen[0].doc_id)}`, { data: { role: 'detail', level: 'Site office' } })
    expect(edit.ok()).toBe(true)
    project = await edit.json()
    expect(project.docs.find((d: { doc_id: string }) => d.doc_id === chosen[0].doc_id)).toMatchObject({ role: 'detail', level: 'Site office', role_source: 'user' })
    const overview = await request.get(`/api/projects/${id}/overview`, { timeout: 60_000 })
    expect(overview.ok()).toBe(true)
    const result = await overview.json()
    expect(result.project_id).toBe(id)
    for (const key of ['levels', 'agreements', 'mistakes', 'coverage']) expect(Array.isArray(result[key]), key).toBe(true)
    for (const key of ['storeys', 'rooms', 'doors', 'windows', 'floor_area_m2']) expect(result.totals).toHaveProperty(key)
    for (const issue of result.mistakes) {
      expect(issue.doc_ids.length).toBeGreaterThan(0)
      expect(issue.check).toBeTruthy()
      expect(issue.evidence.kind).toBeTruthy()
    }
    await test.info().attach('project-overview.json', { body: JSON.stringify(result, null, 2), contentType: 'application/json' })
    const rename = await request.patch(`/api/projects/${id}`, { data: { name: `${name} renamed` } })
    expect(rename.ok()).toBe(true)
    await page.goto(`/#/projects?project=${id}`)
    await expect(page.getByText(`${name} renamed`, { exact: true }).first()).toBeVisible()
    const chat = await request.post('/api/chats', { data: { project_id: id } })
    expect(chat.ok()).toBe(true)
    const createdChat = await chat.json()
    expect(createdChat.project_id).toBe(id)
    const answerResponse = await request.post(`/api/chats/${createdChat.id}/messages`, { data: { content: 'Which documents are in this project?' }, timeout: 90_000 })
    expect(answerResponse.ok()).toBe(true)
    const stream = await answerResponse.text()
    expect(stream).toContain('event: answer')
    await page.goto(`/#/chat?chat=${createdChat.id}`)
    await expect(page.getByTestId('answer-card')).toBeVisible({ timeout: 30_000 })
    const remove = await request.delete(`/api/projects/${id}/docs/${encodeURIComponent(chosen[0].doc_id)}`)
    expect(remove.ok()).toBe(true)
    expect((await remove.json()).docs).toHaveLength(chosen.length - 1)
  } finally {
    const remove = await request.delete(`/api/projects/${id}`)
    expect(remove.ok(), 'Only delete this test-created project').toBe(true)
  }
})
