import { expect, test } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import { resolve } from 'node:path'
import { demoDocument, makeDemoAnswer } from '../src/mock/handler'

test('one live thinking row expands steps, respects reduced motion and collapses after the answer', async ({ page }) => {
  await page.setViewportSize({ width: 1598, height: 1004 })
  await page.routeWebSocket('**/ws', () => {})
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/docs') return route.fulfill({ json: { sources: [{ source: 'demo', docs: [demoDocument] }] } })
    if (path === '/api/chats' && route.request().method() === 'POST') return route.fulfill({ json: { id: 'thinking-demo' } })
    if (path === '/api/projects') return route.fulfill({ json: { projects: [] } })
    return route.fulfill({ json: { chats: [] } })
  })
  // A controllable local stub engine: exercise the actual SSE decoder while the response stays open.
  await page.addInitScript(() => {
    const original = window.fetch.bind(window)
    window.fetch = async (input, init) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
      if (/\/api\/chats\/[^/]+\/messages$/.test(url)) {
        const stream = new ReadableStream<Uint8Array>({ start(controller) {
          const host = window as typeof window & { thinkingEvent?: (event: string, value: unknown) => void }
          host.thinkingEvent = (event, value) => {
            controller.enqueue(new TextEncoder().encode(`event: ${event}\ndata: ${JSON.stringify(value)}\n\n`))
            if (event === 'answer') controller.close()
          }
          host.thinkingEvent('status', { text: 'Thinking…' })
          host.thinkingEvent('status', { text: 'Searching: EI 60 stair core' })
        } })
        return new Response(stream, { headers: { 'Content-Type': 'text/event-stream' } })
      }
      return original(input, init)
    }
  })
  await page.goto('/#/chat')
  const composer = page.getByRole('combobox', { name: 'Ask about your drawings' })
  await composer.fill('@Garden')
  await page.getByRole('option').filter({ hasText: demoDocument.title }).click()
  await composer.fill('What rating do the stair core doors need?')
  await page.getByRole('button', { name: 'Send question', exact: true }).click()
  const row = page.locator('.pending-exchange .thinking-row')
  await expect(row.locator('[role="status"]')).toHaveText('Searching: EI 60 stair core')
  await expect(row).not.toHaveAttribute('open')
  await expect(page.locator('.pending-exchange summary')).toHaveCount(1)
  await expect(page.locator('.answer-skeleton')).toHaveCount(0)
  await expect(row.locator('.thinking-mark')).toHaveCSS('width', '24px')
  await expect(row.locator('.thinking-mark')).toHaveCSS('height', '24px')
  await expect(row.locator('.thinking-glyph img')).toBeVisible()
  await expect(row.locator('.thinking-glyph img')).toHaveJSProperty('complete', true)
  expect(await row.locator('.thinking-glyph img').evaluate((node) => (node as HTMLImageElement).naturalWidth)).toBeGreaterThan(0)
  expect(await row.locator('summary').evaluate((node) => getComputedStyle(node, '::before').content)).toBe('none')
  expect(await row.locator('.thinking-text').evaluate((node) => getComputedStyle(node, '::after').animationName)).toBe('thinking-shimmer')
  const output = resolve(import.meta.dirname, '../../results/final/THINKING')
  mkdirSync(output, { recursive: true })
  await expect(page.locator('.pending-exchange')).toHaveCSS('opacity', '1')
  await page.screenshot({ path: resolve(output, 'thinking.png') })
  await row.locator('summary').click()
  await expect(row.getByRole('list', { name: 'Steps so far' })).toBeVisible()
  await row.locator('summary').click()
  await page.emulateMedia({ reducedMotion: 'reduce' })
  expect(await row.locator('.thinking-text').evaluate((node) => getComputedStyle(node, '::after').animationName)).toBe('none')
  await page.evaluate(() => (window as typeof window & { thinkingEvent: (event: string, value: unknown) => void }).thinkingEvent('trace', {
    step: 'read', detail: 'Reading: drawing page 1', ms: 0, model: null, cost_usd: 0,
  }))
  await expect(row.locator('[role="status"]')).toHaveText('Reading: drawing page 1')
  // Failed deployed brand assets must leave a visible inline mark.
  await row.locator('img').evaluate((image) => image.dispatchEvent(new Event('error')))
  await expect(row.locator('.thinking-mark svg')).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: resolve(output, 'thinking-mobile-fallback.png') })
  expect(await row.locator('summary').evaluate((node) => node.getBoundingClientRect().left)).toBeGreaterThanOrEqual(0)
  const answer = makeDemoAnswer('What rating do the stair core doors need?')
  answer.trace = [{ step: 'read', detail: 'Reading: drawing page 1', ms: 0, model: null, cost_usd: 0 }]
  await page.evaluate((value) => (window as typeof window & { thinkingEvent: (event: string, value: unknown) => void }).thinkingEvent('answer', value), answer)
  await expect(page.locator('.pending-exchange')).toHaveCount(0)
  const completed = page.locator('[data-testid="answer-card"] .thinking-row')
  await expect(completed.locator('summary')).toHaveText('Show thought process')
  await expect(completed).not.toHaveAttribute('open')
  await expect(completed.locator('.thinking-mark')).toBeVisible()
  await completed.locator('summary').click()
  await expect(completed.getByText('Reading: drawing page 1', { exact: true })).toBeVisible()
})
