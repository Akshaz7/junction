import { expect, test, type APIRequestContext } from '@playwright/test'
import type { FileDocument } from '../src/components/data-screen'
import type { ChangeFeedEntry } from '../src/lib/types'

// Every document, revision, change, upload and chat comes from the running API.
// The only browser shim is the native AR bridge, so unavailable AR controls can be checked.
type FolderNode = { name: string; path: string; count: number; children: FolderNode[] }
async function read<T>(request: APIRequestContext, path: string): Promise<T> {
  const response = await request.get(path)
  expect(response.ok(), `${path}: ${response.status()}`).toBe(true)
  return response.json() as Promise<T>
}
async function documents(request: APIRequestContext) {
  const result = await read<{ sources: { docs: FileDocument[] }[] }>(request, '/api/docs')
  return result.sources.flatMap((source) => source.docs)
}
function dateGroup(value?: string | null) {
  const date = new Date(value || '')
  if (Number.isNaN(date.getTime())) return 'Date unavailable'
  const today = new Date(); today.setHours(0, 0, 0, 0)
  const yesterday = new Date(today); yesterday.setDate(yesterday.getDate() - 1)
  const day = new Date(date); day.setHours(0, 0, 0, 0)
  return day.getTime() === today.getTime() ? 'Today' : day.getTime() === yesterday.getTime() ? 'Yesterday' : date.toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })
}

test('API folder hierarchy, file facts and older versions open the matching drawing', async ({ page, request }) => {
  const docs = await documents(request)
  const tree = await read<{ folders: FolderNode[] }>(request, '/api/folders')
  const doc = docs.find((row) => row.versions && row.versions.length > 1 && row.doc_id === row.versions.at(-1)?.doc_id && row.size != null && row.folder)
  expect(doc, 'The real dataset must include a versioned drawing with metadata').toBeTruthy()
  const path = doc!.folder!
  const root = tree.folders.find((node) => path === node.path || path.startsWith(`${node.path}/`))!
  await page.goto('/#/data')
  await expect(page.getByText('Connected workspace', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: `Open ${root.path} folder`, exact: true }).click()
  let branch = root
  while (branch.path !== path) {
    branch = branch.children.find((child) => path === child.path || path.startsWith(`${child.path}/`))!
    await page.getByRole('button', { name: `Open ${branch.path} folder`, exact: true }).click()
  }
  await expect(page.getByRole('button', { name: `Open ${path} folder`, exact: true })).toHaveAttribute('aria-current', 'page')
  await expect(page.locator('.data-files > header')).toContainText(path)
  await page.getByRole('searchbox', { name: 'Search documents' }).fill(doc!.doc_id)
  const row = page.locator(`.data-file-row[data-doc-id="${doc!.doc_id}"]`)
  await expect(row).toBeVisible()
  const size = doc!.size!
  await expect(row.getByLabel('File size', { exact: true })).toHaveText(size < 1024 ? `${size} B` : size < 1024 * 1024 ? `${(size / 1024).toFixed(1)} KB` : `${(size / (1024 * 1024)).toFixed(1)} MB`)
  await expect(row.getByLabel('File date', { exact: true })).toHaveAttribute('datetime', doc!.date || doc!.updated_at!)
  await expect(row).toContainText(`${doc!.version_count} versions`)
  const versions = row.getByRole('combobox', { name: `Versions of ${doc!.title}`, exact: true })
  const older = doc!.versions![0]
  await expect(versions.getByRole('option')).toHaveCount(doc!.versions!.length)
  await versions.selectOption(older.doc_id)
  const detail = page.locator('aside.data-detail')
  const resolved = await request.get(`/api/docs/${encodeURIComponent(older.doc_id)}`)
  const title = resolved.ok() ? (await resolved.json() as FileDocument).title : `${doc!.title} (${older.label})`
  await expect(detail.getByRole('heading', { name: title, exact: true })).toBeVisible()
  await expect(detail.locator('img').first()).toHaveAttribute('src', `/api/docs/${encodeURIComponent(older.doc_id)}/pages/1/image`)
})

test('changes use real calendar dates and combined type, folder and search filters', async ({ page, request }) => {
  const docs = await documents(request)
  const { changes } = await read<{ changes: ChangeFeedEntry[] }>(request, '/api/changes')
  expect(changes.length).toBeGreaterThan(0)
  const revision = changes.find((entry) => entry.type === 'new_version' && docs.some((doc) => doc.doc_id === entry.doc_b && doc.folder))!
  expect(revision, 'The real changes feed must contain a drawing revision').toBeTruthy()
  const folder = docs.find((doc) => doc.doc_id === revision.doc_b)!.folder!
  await page.goto('/#/changes')
  await expect(page.locator('.changes-refresh')).toContainText('Checked at')
  for (const entry of changes) {
    const group = page.getByRole('region', { name: `Changes: ${dateGroup(entry.created_at)}`, exact: true })
    await expect(group.locator(`[data-change-id="${entry.id}"]`)).toHaveCount(1)
  }
  await page.getByRole('combobox', { name: 'Change type', exact: true }).selectOption('new_version')
  await page.getByRole('combobox', { name: 'Change folder', exact: true }).selectOption(folder)
  const expected = changes.filter((entry) => entry.type === 'new_version' && (docs.find((doc) => doc.doc_id === entry.doc_b || doc.doc_id === entry.summary.doc_id) || docs.find((doc) => doc.doc_id === entry.doc_a))?.folder === folder)
  await expect(page.locator('.change-row')).toHaveCount(expected.length)
  await expect(page.locator('.rule-change-card')).toHaveCount(0)
  await page.locator(`.change-row[data-change-id="${revision.id}"]`).click()
  await expect(page.locator('.comparison-box')).toBeVisible()
  await page.getByRole('searchbox', { name: 'Search changes' }).fill(`no-match-${Date.now()}`)
  await expect(page.getByText('No changes match these filters.', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Clear change filters', exact: true }).click()
  await expect(page.getByRole('combobox', { name: 'Change type', exact: true })).toHaveValue('')
  await expect(page.getByRole('combobox', { name: 'Change folder', exact: true })).toHaveValue('')
  await expect(page.locator('.change-row')).toHaveCount(changes.filter((entry) => entry.type !== 'rule_change').length)
})

test('upload polls ingestion, shows progress, opens the ready file and hides AR without a scene', async ({ page, request }) => {
  test.setTimeout(60_000)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.addInitScript(() => {
    Object.defineProperty(window, 'webkit', { value: { messageHandlers: { ar: { postMessage() {} } } } })
  })
  await page.goto('/#/data')
  await expect(page.getByText('Connected workspace', { exact: true })).toBeVisible()
  const name = `web3-notes-${Date.now()}-generated-for-demo.pdf`
  // A text-only PDF generated for demo exercises real rendering and text ingestion.
  const line = 'generated for demo construction meeting notes check drawing references before site work'
  const stream = `BT /F1 10 Tf 40 750 Td 14 TL ${Array.from({ length: 36 }, () => `(${line}) Tj T*`).join(' ')} ET`
  const objects = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>', '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>', '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>', `<< /Length ${Buffer.byteLength(stream)} >>\nstream\n${stream}\nendstream`]
  let pdf = '%PDF-1.4\n'
  const offsets = [0]
  objects.forEach((object, index) => { offsets.push(Buffer.byteLength(pdf)); pdf += `${index + 1} 0 obj\n${object}\nendobj\n` })
  const xref = Buffer.byteLength(pdf)
  pdf += `xref\n0 6\n0000000000 65535 f \n${offsets.slice(1).map((offset) => `${String(offset).padStart(10, '0')} 00000 n \n`).join('')}trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`
  const receiptResponse = page.waitForResponse((response) => response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/upload')
  const ingestResponse = page.waitForResponse((response) => new URL(response.url()).pathname.endsWith('/ingest'))
  await page.getByRole('button', { name: 'Upload', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Upload a drawing' })
  await dialog.getByLabel('Choose a drawing').setInputFiles({ name, mimeType: 'application/pdf', buffer: Buffer.from(pdf) })
  const receipt = await receiptResponse
  expect(receipt.ok()).toBe(true)
  const { doc_id, status } = await receipt.json() as { doc_id: string; status: string }
  expect(status, 'The done test requires enabled ingestion').toBe('ingesting')
  expect((await ingestResponse).ok()).toBe(true)
  // W-65: the file opens as soon as pages and text are readable, while 3D/plan-map work may still run.
  await expect(dialog.getByRole('status').filter({ hasText: 'Ready' }).first()).toBeVisible({ timeout: 45_000 })
  await dialog.getByRole('button', { name: 'Open', exact: true }).click()
  const detail = page.locator('aside.data-detail')
  await expect(detail.getByRole('heading', { name: /web3-notes-\d+/ })).toBeVisible()
  await expect(detail.locator('img').first()).toHaveAttribute('src', `/api/docs/${doc_id}/pages/1/image`)
  await expect.poll(async () => (await read<{ status: string }>(request, `/api/docs/${doc_id}/ingest`)).status, { timeout: 45_000 }).toMatch(/ready|partial/)
  const state = await read<{ status: string; stages: unknown[] }>(request, `/api/docs/${doc_id}/ingest`)
  expect(['ready', 'partial']).toContain(state.status)
  expect(state.stages.length).toBeGreaterThan(0)
  // Check a real non-scene document, independent of whether ingestion produced a scene for the upload.
  const docs = await documents(request)
  const versioned = docs.find((doc) => doc.versions?.length && doc.kind === 'pdf')!
  const scene = await request.get(`/api/docs/${versioned.doc_id}/files/scene.json`)
  expect(scene.status()).toBe(404)
  await page.getByRole('button', { name: 'Close document details' }).click()
  await page.getByRole('searchbox', { name: 'Search documents' }).fill(versioned.doc_id)
  await page.locator(`.data-file-row[data-doc-id="${versioned.doc_id}"] .data-open-file`).click()
  await expect(detail.getByRole('button', { name: 'Show on table', exact: true })).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

for (const title of ['Draft claim', 'Meeting prep', 'Plan work phase', 'Review contract']) {
  test(`${title} starts and persists a real construction chat`, async ({ page, request }) => {
    test.setTimeout(60_000)
    await page.goto('/#/overview')
    const starters = page.getByRole('region', { name: 'Start a question', exact: true })
    for (const label of ['Draft claim', 'Meeting prep', 'Plan work phase', 'Review contract']) await expect(starters.getByRole('button', { name: label, exact: true })).toBeEnabled()
    const chatResponse = page.waitForResponse((response) => response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/chats')
    await starters.getByRole('button', { name: title, exact: true }).click()
    const response = await chatResponse
    expect(response.ok()).toBe(true)
    const { id } = await response.json() as { id: string }
    await expect(page).toHaveURL(new RegExp(`#/chat\\?chat=${id}$`), { timeout: 45_000 })
    const chat = await read<{ title: string; messages: { role: string; content: string }[] }>(request, `/api/chats/${id}`)
    expect(chat.title).toBe(title)
    const question = chat.messages.find((message) => message.role === 'user')!
    expect(question.content).toMatch(/construction/i)
    expect(question.content).toMatch(/citat|cite/i)
    expect(chat.messages.some((message) => message.role === 'assistant')).toBe(true)
    await expect(page.locator('.question-bubble').last()).toHaveText(question.content)
  })
}
