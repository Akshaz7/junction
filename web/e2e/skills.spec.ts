import { expect, test } from '@playwright/test'
import type { Answer } from '../src/lib/types'
import type { Automation, Skill } from '../src/lib/skills'

const docId = 'ifc_bench__ac20-arc'
const question = 'How many windows are there?'
const createdResources = new Set<string>()

// Hooks receive their own timeout budget, before the request fixture is disposed.
// A timed-out test must retain its original error instead of failing in finally.
test.afterEach(async ({ request }) => {
  for (const path of createdResources) {
    const response = await request.delete(path)
    createdResources.delete(path)
    expect(response.status()).toBe(204)
  }
})

test('create a real skill, run it on AC20, and pick its prompt in the composer', async ({ page }) => {
  test.setTimeout(60_000)
  let skillId = ''
  const name = `AC20 windows ${Date.now()}`
    await page.goto('/#/skills')
    const screen = page.getByRole('region', { name: 'Skills', exact: true })
    await expect(screen.getByText('Starter', { exact: true })).toHaveCount(4)
    const create = screen.getByRole('form', { name: 'Create skill' })
    await create.getByLabel('Skill name', { exact: true }).fill(name)
    await create.getByLabel('Skill prompt', { exact: true }).fill(question)
    const saved = page.waitForResponse((response) => response.url().endsWith('/api/skills') && response.request().method() === 'POST')
    await create.getByRole('button', { name: 'Save skill', exact: true }).click()
    const created = await saved
    expect(created.status()).toBe(201)
    skillId = (await created.json() as Skill).id
    createdResources.add(`/api/skills/${skillId}`)
    await screen.getByLabel('Run on drawing', { exact: true }).selectOption(docId)
    const card = screen.locator(`[data-skill-id="${skillId}"]`)
    await expect(card).toContainText(question)
    const running = page.waitForResponse((response) => response.url().endsWith(`/api/skills/${skillId}/run`))
    await card.getByRole('button', { name: 'Run skill', exact: true }).click()
    const result = await running
    expect(result.ok()).toBe(true)
    const { answer } = await result.json() as { answer: Answer }
    expect(answer.answer.abstained).toBe(false)
    expect(answer.doc_ids).toContain(docId)
    await expect(screen.getByRole('region', { name: 'Skill answer' })).toContainText(String(answer.answer.value))
    await page.goto('/#/chat')
    const add = page.getByRole('button', { name: 'Add to question', exact: true })
    await expect(page.getByRole('combobox', { name: 'Use a skill' })).toHaveCount(0)
    await add.click()
    const menu = page.getByRole('dialog', { name: 'Add to question', exact: true })
    await expect(menu.getByRole('button', { name: 'Include a document', exact: true })).toBeEnabled()
    await page.keyboard.press('Escape')
    await expect(menu).toHaveCount(0)
    await expect(add).toBeFocused()
    await add.click()
    await menu.getByRole('button', { name: 'Include a document', exact: true }).click()
    const draft = page.getByRole('combobox', { name: 'Ask about your drawings' })
    await expect(draft).toHaveValue('@')
    await expect(page.getByRole('listbox', { name: 'Documents', exact: true })).toBeVisible()
    await draft.fill('')
    await add.click()
    const picker = menu.getByRole('combobox', { name: 'Use a skill' })
    await expect(picker).toBeEnabled()
    await picker.selectOption(skillId)
    await expect(page.getByRole('combobox', { name: 'Ask about your drawings' })).toHaveValue(question)
    await expect(menu).toHaveCount(0)
    await expect(page.getByRole('combobox', { name: 'Ask about your drawings' })).toBeFocused()
})

test('create a real automation, run it on AC20, and display and export its persisted report', async ({ page, request }) => {
  test.setTimeout(60_000)
  let automationId = ''
  const name = `AC20 daily ${Date.now()}`
    await page.goto('/#/automations')
    const screen = page.getByRole('region', { name: 'Automations', exact: true })
    const create = screen.getByRole('form', { name: 'Create automation' })
    await create.getByLabel('Automation name', { exact: true }).fill(name)
    await create.getByLabel('Automation prompt', { exact: true }).fill(question)
    await create.getByLabel('Automation drawing', { exact: true }).selectOption(docId)
    await create.getByLabel('Schedule', { exact: true }).selectOption('1440')
    const saved = page.waitForResponse((response) => response.url().endsWith('/api/automations') && response.request().method() === 'POST')
    await create.getByRole('button', { name: 'Save automation', exact: true }).click()
    const created = await saved
    expect(created.status()).toBe(201)
    automationId = (await created.json() as Automation).id
    createdResources.add(`/api/automations/${automationId}`)
    const card = screen.locator(`[data-automation-id="${automationId}"]`)
    await expect(card).toContainText('Not run yet')
    const running = page.waitForResponse((response) => response.url().endsWith(`/api/automations/${automationId}/run`))
    await card.getByRole('button', { name: 'Run now', exact: true }).click()
    const response = await running
    expect(response.ok()).toBe(true)
    const result = await response.json() as Automation
    expect(result.last_report?.ok).toBe(true)
    const answer = result.last_report!.answer!
    expect(answer.answer.abstained).toBe(false)
    const report = screen.getByRole('region', { name: 'Last automation report' })
    await expect(report.getByRole('heading', { name, exact: true })).toBeVisible()
    await expect(report).toContainText(String(answer.answer.value))
    await expect(card).not.toContainText('Not run yet')
    const downloadPromise = page.waitForEvent('download')
    await report.getByRole('button', { name: 'Export .md', exact: true }).click()
    const download = await downloadPromise
    expect(download.suggestedFilename()).toMatch(/\.md$/)
    const persisted = await request.get(`/api/automations/${automationId}/report.md`)
    expect(persisted.ok()).toBe(true)
    expect(await persisted.text()).toBe(result.last_report!.markdown)
})
