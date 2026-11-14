import { readFileSync } from 'node:fs'
import { basename, resolve } from 'node:path'
import { test, expect, production, chooseDocument, ask, fixtureManifest, repoRoot } from './final-helpers'
import type { Document } from '../src/lib/types'

// Contract: handoff/F-PROJECTS-CONTRACT.md v1. Enable when both feature branches have commits.
test.setTimeout(360_000)
test.use({ viewport: { width: 1440, height: 1000 } })
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
  await page.getByRole('tab', { name: 'Files', exact: true }).click()
  await expect(page.locator(`[data-doc-id="${project.docs[0].doc_id}"]`)).toBeVisible()
  await page.screenshot({ path: test.info().outputPath('demo-project.png') })
})

test('[PROJECTS] Create, attach, classify, edit metadata, overview, project chat, remove and delete', async ({ page, request }) => {
  test.skip(production, 'Production is read-only: project writes forbidden')
  const chosen: Document[] = []
  for (const kind of ['ifc', 'dxf', 'raster']) chosen.push(await chooseDocument(request, kind))
  const name = `E2E project ${Date.now()}`
  await page.goto('/#/projects')
  await page.getByRole('button', { name: 'New project', exact: true }).first().click()
  const dialog = page.getByRole('dialog', { name: 'New project', exact: true })
  await dialog.getByLabel('Name', { exact: true }).fill(name)
  await dialog.getByRole('button', { name: 'Add from library', exact: true }).click()
  await dialog.getByRole('searchbox', { name: 'Search the library' }).fill(chosen[0].doc_id)
  await dialog.getByRole('option').click()
  const created = page.waitForResponse((r) => new URL(r.url()).pathname === '/api/projects' && r.request().method() === 'POST')
  await dialog.getByRole('button', { name: /^Create/ }).click()
  const create = await created
  expect(create.ok()).toBe(true)
  let project = await create.json()
  const id = project.id
  expect(project.name).toBe(name)
  let deleted = false
  try {
    await expect(page.getByRole('heading', { name, exact: true })).toBeVisible()
    await page.getByRole('tab', { name: 'Files', exact: true }).click()
    await page.getByRole('button', { name: 'Add files', exact: true }).first().click()
    const adding = page.getByRole('dialog', { name: 'Add files', exact: true })
    await adding.getByRole('button', { name: 'Add from library', exact: true }).click()
    for (const doc of chosen.slice(1)) {
      await adding.getByRole('searchbox', { name: 'Search the library' }).fill(doc.doc_id)
      await adding.getByRole('option').click()
    }
    const added = page.waitForResponse((r) => new URL(r.url()).pathname === `/api/projects/${id}/docs` && r.request().method() === 'POST')
    await adding.getByRole('button', { name: 'Add 2 files', exact: true }).click()
    const add = await added
    expect(add.ok()).toBe(true)
    project = await add.json()
    expect(project.docs.map((d: { doc_id: string }) => d.doc_id).sort()).toEqual(chosen.map((d) => d.doc_id).sort())
    const roles = ['model', 'plan', 'section', 'elevation', 'detail', 'schedule', 'scan', 'photo', 'spec', 'revision', 'other']
    for (const doc of project.docs) {
      expect(roles).toContain(doc.role)
      expect(doc.role_source).toBe('auto')
    }
    const row = page.locator(`[data-doc-id="${chosen[0].doc_id}"]`)
    const edited = page.waitForResponse((r) => new URL(r.url()).pathname === `/api/projects/${id}/docs/${chosen[0].doc_id}` && r.request().method() === 'PATCH')
    await row.getByRole('combobox').selectOption('detail')
    expect((await edited).ok()).toBe(true)
    await expect(row.getByRole('combobox')).toBeEnabled()
    const level = row.getByRole('textbox')
    await level.fill('Site office')
    const levelEdited = page.waitForResponse((r) => new URL(r.url()).pathname === `/api/projects/${id}/docs/${chosen[0].doc_id}` && r.request().method() === 'PATCH')
    await level.press('Enter')
    const edit = await levelEdited
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
    await page.getByRole('tab', { name: 'Overview', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Mistakes found', exact: true })).toBeVisible({ timeout: 60_000 })
    await page.screenshot({ path: test.info().outputPath('project-overview.png') })
    await page.getByLabel('Project actions', { exact: true }).click()
    await page.getByRole('button', { name: 'Rename', exact: true }).click()
    await page.getByRole('textbox', { name: 'Project name', exact: true }).fill(`${name} renamed`)
    const renamed = page.waitForResponse((r) => new URL(r.url()).pathname === `/api/projects/${id}` && r.request().method() === 'PATCH')
    await page.getByRole('button', { name: 'Save', exact: true }).click()
    const rename = await renamed
    expect(rename.ok()).toBe(true)
    await expect(page.getByText(`${name} renamed`, { exact: true }).first()).toBeVisible()
    await page.goto(`/#/chat?project=${id}`)
    await expect(page.getByRole('complementary', { name: 'Project content', exact: true })).toBeVisible()
    const chatCreated = page.waitForResponse((r) => new URL(r.url()).pathname === '/api/chats' && r.request().method() === 'POST')
    const answer = await ask(page, 'How many doors across all documents?')
    const createdChat = await (await chatCreated).json()
    expect(createdChat.project_id).toBe(id)
    expect([...answer.doc_ids].sort()).toEqual(chosen.map((doc) => doc.doc_id).sort())
    expect(answer.citations.length).toBeGreaterThan(0)
    expect(answer.reasoning?.steps.length).toBeGreaterThan(0)
    await page.goto(`/#/projects?id=${id}&tab=files`)
    const removed = page.waitForResponse((r) => new URL(r.url()).pathname === `/api/projects/${id}/docs/${chosen[0].doc_id}` && r.request().method() === 'DELETE')
    await page.locator(`[data-doc-id="${chosen[0].doc_id}"]`).getByRole('button', { name: /^Remove/ }).click()
    const remove = await removed
    expect(remove.ok()).toBe(true)
    expect((await remove.json()).docs).toHaveLength(chosen.length - 1)
    await expect(page.locator(`[data-doc-id="${chosen[0].doc_id}"]`)).toHaveCount(0)
    await page.getByLabel('Project actions', { exact: true }).click()
    await page.getByRole('button', { name: 'Delete project', exact: true }).click()
    const deletion = page.waitForResponse((r) => new URL(r.url()).pathname === `/api/projects/${id}` && r.request().method() === 'DELETE')
    await page.getByRole('button', { name: 'Delete for good?', exact: true }).click()
    expect((await deletion).ok()).toBe(true)
    deleted = true
    await expect(page).toHaveURL(/#\/projects$/)
  } finally {
    if (!deleted) {
      const remove = await request.delete(`/api/projects/${id}`)
      expect(remove.ok(), 'Only delete this test-created project').toBe(true)
    }
  }
})

test('[PROJECTS] Upload a real file directly to a project and show ingestion status', async ({ page, request }) => {
  test.skip(production, 'Production is read-only: no project uploads')
  const create = await request.post('/api/projects', { data: { name: `E2E upload project ${Date.now()}` } })
  expect(create.ok()).toBe(true)
  const { id } = await create.json()
  try {
    await page.goto(`/#/projects?id=${id}&tab=files`)
    await page.getByTestId('files-empty').getByRole('button', { name: 'Add files', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: 'Add files', exact: true })
    const [relative] = fixtureManifest['.dxf']
    await dialog.getByLabel('Choose files to upload', { exact: true }).setInputFiles({
      name: `e2e-project-${Date.now()}-${basename(relative)}`, mimeType: 'application/octet-stream', buffer: readFileSync(resolve(repoRoot, relative)),
    })
    const uploaded = page.waitForResponse((r) => new URL(r.url()).pathname === `/api/projects/${id}/upload`)
    await dialog.getByRole('button', { name: 'Add 1 file', exact: true }).click()
    const response = await uploaded
    expect(response.ok()).toBe(true)
    const receipt = await response.json()
    expect(receipt.project.docs.some((doc: { doc_id: string }) => doc.doc_id === receipt.doc_id)).toBe(true)
    const row = page.locator(`[data-doc-id="${receipt.doc_id}"]`)
    await expect(row).toBeVisible()
    await expect(row).toContainText(/Reading the file|Set automatically/)
    await expect.poll(async () => (await (await request.get(`/api/docs/${receipt.doc_id}/ingest`)).json()).status,
      { timeout: 285_000, intervals: [1000, 2000, 5000] }).toMatch(/^(ready|partial)$/)
    await expect(row).toContainText('Set automatically', { timeout: 30_000 })
    await page.screenshot({ path: test.info().outputPath('project-upload-ready.png') })
  } finally {
    expect((await request.delete(`/api/projects/${id}`)).ok()).toBe(true)
  }
})

test('[PROJECTS] Phone keeps Projects, files, overview and project chat within 390x844', async ({ page, request }) => {
  const response = await request.get('/api/projects')
  expect(response.ok()).toBe(true)
  const { projects } = await response.json()
  expect(projects.length).toBeGreaterThan(0)
  const id = projects[0].id
  await page.setViewportSize({ width: 390, height: 844 })
  for (const route of ['projects', `projects?id=${id}`, `projects?id=${id}&tab=files`, `projects?id=${id}&tab=overview`, `chat?project=${id}`]) {
    await page.goto(`/#/${route}`)
    await expect(page.getByRole('navigation', { name: 'Mobile navigation' })).toBeVisible()
    if (route.startsWith('chat')) await expect(page.getByRole('combobox', { name: 'Ask about your drawings' })).toBeEnabled()
    else await expect(page.getByRole('heading', { level: 1 }).last()).toBeVisible()
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(1)
  }
  await expect(page.getByRole('combobox', { name: 'Ask about your drawings' })).toBeEnabled()
  await page.screenshot({ path: test.info().outputPath('project-phone.png') })
})
