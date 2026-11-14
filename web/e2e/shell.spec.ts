import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { handleMockRequest } from '../src/mock/handler'

const navItems = ['Overview', 'Chat', 'Changes', 'Data', 'Compare', 'Library', 'Tools', 'Accuracy']

test('workspace shell exposes every route and restores it on reload', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveTitle('Stoa Pro')
  const navigation = page.getByRole('navigation', { name: 'Workspace navigation', exact: true })
  await expect(page.getByRole('link', { name: 'Stoa Pro home' })).toHaveText('Pro')
  for (const label of navItems.filter((item) => item !== 'Accuracy')) {
    const link = navigation.getByRole('link', { name: label, exact: true })
    await expect(link).toBeVisible()
    await link.click()
    await expect(link).toHaveAttribute('aria-current', 'page')
    await expect(page.getByRole('heading', { name: label, exact: true, level: 1 })).toBeVisible()
    await expect(page).toHaveURL(new RegExp(`#/${label.toLowerCase()}$`))
  }
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Tools', exact: true, level: 1 })).toBeVisible()
  await page.goBack()
  await expect(page.getByRole('heading', { name: 'Library', exact: true, level: 1 })).toBeVisible()
})

test('ten root CSS variables equal the supplied reference tokens', async ({ page }) => {
  const reference = readFileSync(new URL('../../refs/stoa-hero/theme-tokens.css', import.meta.url), 'utf8')
  const names = ['--sidebar', '--sidebar-foreground', '--background', '--card', '--foreground', '--primary', '--muted-foreground', '--border', '--radius-control', '--spacing-rail-width']
  const expected = Object.fromEntries(names.map((name) => {
    const value = reference.match(new RegExp(`^\\s*${name}:\\s*([^;]+);`, 'm'))?.[1].trim()
    if (!value) throw new Error(`Missing reference token: ${name}`)
    return [name, value]
  }))
  await page.goto('/')
  const actual = await page.evaluate((tokens) => {
    const root = getComputedStyle(document.documentElement)
    return Object.fromEntries(tokens.map((name) => [name, root.getPropertyValue(name).trim()]))
  }, names)
  expect(actual).toEqual(expected)
})

test('phone navigation keeps all pages reachable without horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  const navigation = page.getByRole('navigation', { name: 'Mobile navigation', exact: true })
  await expect(navigation).toBeVisible()
  for (const label of navItems.filter((item) => item !== 'Accuracy')) {
    const underMore = ['Compare', 'Library', 'Tools', 'Accuracy'].includes(label)
    const more = navigation.getByText('More', { exact: true })
    if (underMore) await more.click()
    await navigation.getByRole('link', { name: label, exact: true }).click()
    await expect(page.getByRole('heading', { name: label, exact: true, level: 1 })).toBeVisible()
    await expect(page).toHaveURL(new RegExp(`#/${label.toLowerCase()}$`))
    if (underMore) {
      // Navigation closes More; reopen it to inspect the active link as a user would.
      await expect(navigation.locator('details')).not.toHaveAttribute('open')
      await more.click()
      await expect(navigation.getByRole('link', { name: label, exact: true })).toBeVisible()
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    }
    await expect(navigation.getByRole('link', { name: label, exact: true })).toHaveAttribute('aria-current', 'page')
    if (underMore) await more.click()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  }
})

test('demo chat and document navigation', async ({ page }) => {
  await page.route('**/api/**', async (route) => {
    const req = route.request()
    const response = await handleMockRequest(new Request(req.url(), {
      method: req.method(), ...(req.postData() ? { body: req.postData()! } : {}),
    }))
    if (!response) return route.continue()
    await route.fulfill({ status: response.status, contentType: response.headers.get('content-type') ?? undefined, body: await response.text() })
  })
  await page.goto('/#/chat')
  await expect(page).toHaveTitle('Stoa Pro')
  await page.getByRole('button', { name: /Count something on a plan/ }).click()
  await page.getByRole('combobox', { name: 'Ask about your drawings' }).press('Enter')
  await page.getByTestId('need-document').getByRole('button', { name: 'Choose a document' }).click()
  await page.getByRole('option').first().click()
  await expect(page.getByText('2 windows', { exact: true })).toBeVisible()
  await page.locator('.sources-summary').click()
  await expect(page.locator('.sources-detail')).toContainText(/Page \d/)
  await page.getByRole('navigation', { name: 'Workspace navigation', exact: true }).getByRole('link', { name: 'Data', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Garden room — generated for demo' })).toBeVisible()
  await page.getByRole('searchbox', { name: 'Search documents' }).fill('missing')
  await expect(page.getByText('No documents found.')).toBeVisible()
})
