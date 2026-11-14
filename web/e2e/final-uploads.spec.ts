import { readFileSync } from 'node:fs'
import { basename, resolve } from 'node:path'
import { test, expect, production, fixtureManifest, repoRoot, ask } from './final-helpers'

test.setTimeout(360_000) // LONG: real ingestion can take up to the server's five-minute deadline.
test.use({ viewport: { width: 1440, height: 1000 } })

// IFC is deliberately last: it was randomly reserved before development and must stay unseen until this test.
for (const extension of ['.png', '.jpg', '.dxf', '.ifc']) {
  test(`[SERVER] Upload real ${extension} file, show status, finish ingestion and answer first question${extension === '.ifc' ? ' (reserved unseen file)' : ''}`, async ({ page, request }) => {
    test.skip(production, 'Production is read-only: no uploads or new chats')
    const [relative, bytes] = fixtureManifest[extension]
    test.info().annotations.push({ type: 'real-file', description: `${relative} (${bytes} bytes)` })
    await page.goto('/#/data')
    await page.getByRole('button', { name: 'Upload', exact: true }).first().click()
    const sent = page.waitForResponse((r) => new URL(r.url()).pathname === '/api/upload' && r.request().method() === 'POST')
    await page.getByLabel('Choose a drawing', { exact: true }).setInputFiles({
      name: `e2e-${Date.now()}-${basename(relative)}`,
      mimeType: extension === '.png' ? 'image/png' : extension === '.jpg' ? 'image/jpeg' : 'application/octet-stream',
      buffer: readFileSync(resolve(repoRoot, relative)),
    })
    const response = await sent
    expect(response.ok(), `Upload HTTP ${response.status()}`).toBe(true)
    const receipt = await response.json()
    expect(receipt.doc_id).toBeTruthy()
    const dialog = page.getByRole('dialog').filter({ has: page.getByRole('button', { name: 'Close upload dialog' }) })
    await expect(dialog).toBeVisible()
    await expect(dialog).toContainText(/upload|processing|preparing|ready|read/i)
    let state: Record<string, unknown> = {}
    await expect.poll(async () => {
      const res = await request.get(`/api/docs/${receipt.doc_id}/ingest`)
      expect(res.ok()).toBe(true)
      state = await res.json()
      return state.status
    }, { timeout: 270_000, intervals: [1000, 2000, 5000], message: 'Real ingestion must terminate' }).not.toBe('running')
    await test.info().attach('ingest.json', { body: JSON.stringify({ fixture: relative, receipt, state }, null, 2), contentType: 'application/json' })
    expect(state.status, JSON.stringify(state)).toMatch(/^(ready|partial)$/)
    await expect(dialog.getByRole('button', { name: 'Open', exact: true })).toBeEnabled({ timeout: 20_000 })
    await page.screenshot({ path: test.info().outputPath('upload-ready.png') })
    await dialog.getByRole('button', { name: 'Open', exact: true }).click()
    const detail = page.getByRole('complementary', { name: 'Document details', exact: true })
    await detail.getByRole('button', { name: 'Ask about it', exact: true }).first().click()
    await expect(page.getByLabel('Selected documents')).toBeVisible()
    const answer = await ask(page, 'How many doors are there?')
    expect(answer.doc_ids).toContain(receipt.doc_id)
    expect(answer.answer.text_md.trim().length).toBeGreaterThan(0)
    expect(answer.answer.abstained, 'Readable uploads should answer their first question').toBe(false)
    expect(answer.reasoning?.steps?.length, 'First answer explains its evidence').toBeGreaterThan(0)
    expect(answer.citations.length, 'First answer is cited').toBeGreaterThan(0)
  })
}
