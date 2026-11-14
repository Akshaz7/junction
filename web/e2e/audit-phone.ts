import { expect, type Locator, type Page, type TestInfo } from '@playwright/test'

/** Shared helpers for the phone button audit (audit-phone.spec.ts). */
export const routes = ['overview', 'chat', 'changes', 'data', 'compare', 'library', 'tools', 'accuracy'] as const
export type AuditRoute = typeof routes[number]

export interface Finding { where: string; kind: string; detail: string }

export class Audit {
  findings: Finding[] = []
  consoleErrors: string[] = []
  badResponses: string[] = []
  requests = 0
  constructor(readonly page: Page, readonly label: string) {
    page.on('console', (message) => { if (message.type() === 'error') this.consoleErrors.push(message.text()) })
    page.on('pageerror', (error) => this.consoleErrors.push(`pageerror: ${error.message}`))
    page.on('request', (request) => { if (/\/api\//.test(request.url())) this.requests++ })
    page.on('response', (response) => {
      if (/\/api\//.test(response.url()) && response.status() >= 400) this.badResponses.push(`${response.status()} ${response.request().method()} ${new URL(response.url()).pathname}`)
    })
  }
  add(where: string, kind: string, detail: string) {
    if (!this.findings.some((f) => f.where === where && f.kind === kind && f.detail === detail)) this.findings.push({ where, kind, detail })
  }
  report(testInfo: TestInfo) {
    const text = this.findings.map((f) => `[${f.kind}] ${f.where}: ${f.detail}`).join('\n')
    if (text) console.log(`AUDIT ${this.label}\n${text}`)
    return testInfo.attach(`findings-${this.label}`, { body: text || 'none', contentType: 'text/plain' })
  }
  /** Console errors that are not caused by an intentional request failure. */
  unexpectedConsole() {
    return this.consoleErrors.filter((entry) => !/favicon|ResizeObserver|net::ERR_ABORTED|Failed to load resource/i.test(entry))
  }
}

/** Simulate the iPhone 15 Pro Max notch (59px) and home bar (34px) the native shell supplies. */
export async function installSafeAreas(page: Page) {
  await page.addInitScript(() => {
    document.addEventListener('DOMContentLoaded', () => {
      const style = document.createElement('style')
      style.textContent = ':root{--app-safe-top:59px;--app-safe-bottom:34px}'
      document.head.append(style)
    })
  })
}

export async function openRoute(page: Page, route: string) {
  await page.goto(`/#/${route}`)
  await page.reload()
  await expect(page.getByText('Connected workspace', { exact: true })).toBeVisible({ timeout: 15_000 })
  await page.waitForLoadState('networkidle', { timeout: 8000 }).catch(() => {})
}

const interactive = 'button, a[href], [role=tab], [role=menuitem], [role=button], summary, select, input[type=checkbox], input[type=radio], input[type=range]'

export interface Item { index: number; tag: string; name: string; key: string }

/** Tag visible, enabled interactive elements with data-audit and return descriptors. */
export async function collect(page: Page): Promise<Item[]> {
  return page.evaluate((selector) => {
    document.querySelectorAll('[data-audit]').forEach((node) => node.removeAttribute('data-audit'))
    const items: { index: number; tag: string; name: string; key: string }[] = []
    const seen: Record<string, number> = {}
    let index = 0
    for (const node of Array.from(document.querySelectorAll<HTMLElement>(selector))) {
      const style = getComputedStyle(node), rect = node.getBoundingClientRect()
      if (style.visibility === 'hidden' || style.display === 'none' || rect.width < 1 || rect.height < 1) continue
      if (node.closest('[inert],[hidden],[aria-hidden=true]')) continue
      if ((node as HTMLButtonElement).disabled || node.getAttribute('aria-disabled') === 'true') continue
      if (node.closest('.skip-link') || node.matches('.skip-link')) continue
      const name = (node.getAttribute('aria-label') || node.textContent || node.getAttribute('title') || node.getAttribute('placeholder') || '').trim().replace(/\s+/g, ' ').slice(0, 60)
      const key = `${node.tagName}.${node.className}`
      seen[key] = (seen[key] || 0) + 1
      if (seen[key] > 3) continue // sample repetitive rows (documents, chats)
      node.setAttribute('data-audit', String(index))
      items.push({ index, tag: node.tagName.toLowerCase(), name, key })
      index++
    }
    return items
  }, interactive)
}

export async function signature(page: Page) {
  return page.evaluate(() => {
    const states = Array.from(document.querySelectorAll('[aria-pressed],[aria-expanded],[aria-selected],[aria-current],details')).map((node) =>
      `${node.getAttribute('aria-pressed')}${node.getAttribute('aria-expanded')}${node.getAttribute('aria-selected')}${node.getAttribute('aria-current')}${(node as HTMLDetailsElement).open ?? ''}`).join('|')
    const fields = Array.from(document.querySelectorAll<HTMLInputElement>('input,select,textarea')).map((node) => `${node.value}${node.checked ?? ''}`).join('|')
    return [location.hash, document.body.innerText.length, document.querySelectorAll('*').length, states, fields, document.querySelectorAll('[role=dialog],[role=alertdialog],.document-viewer,.sheet,[popover]:popover-open').length, document.activeElement?.tagName].join('~')
  })
}

export interface Geometry { hit: boolean; notch: boolean; w: number; h: number; covered: string; offscreen: boolean; text: string; inProse: boolean }

export async function geometry(el: Locator): Promise<Geometry> {
  return el.evaluate((node) => {
    node.scrollIntoView({ block: 'center', inline: 'center' })
    const rect = (node.closest('label') ?? node).getBoundingClientRect()
    const x = rect.left + rect.width / 2, y = rect.top + rect.height / 2
    const top = document.elementFromPoint(Math.min(Math.max(x, 0), innerWidth - 1), Math.min(Math.max(y, 0), innerHeight - 1))
    const covered = top && !node.contains(top) && !top.contains(node) ? `${top.tagName.toLowerCase()}.${String((top as HTMLElement).className).slice(0, 40)}` : ''
    // A control may be visually small if its hit area (e.g. a pseudo-element) reaches 44px.
    const reach = (dx: number, dy: number) => {
      const target = document.elementFromPoint(Math.min(Math.max(x + dx, 0), innerWidth - 1), Math.min(Math.max(y + dy, 0), innerHeight - 1))
      return !!target && (node.contains(target) || target.contains(node) || (node.closest('label')?.contains(target) ?? false))
    }
    const hit = (rect.width >= 44 || (reach(-21, 0) && reach(21, 0))) && (rect.height >= 44 || (reach(0, -21) && reach(0, 21)))
    return {
      hit,
      notch: rect.top < 57 || rect.bottom > innerHeight - 32,
      w: Math.round(rect.width), h: Math.round(rect.height), covered,
      offscreen: rect.right < 0 || rect.left > innerWidth + 1 || rect.bottom < 0 || rect.top > innerHeight,
      text: (node.textContent || '').trim().slice(0, 40),
      inProse: !!node.closest('p, li, .answer-text, .markdown') && node.tagName === 'A' || node.classList.contains('citation-chip'),
    }
  })
}

export async function layoutChecks(page: Page, audit: Audit, where: string) {
  const info = await page.evaluate(() => {
    const doc = document.documentElement
    const wide: string[] = []
    for (const node of Array.from(document.querySelectorAll<HTMLElement>('body *'))) {
      const rect = node.getBoundingClientRect()
      if (rect.width && rect.right > innerWidth + 1 && getComputedStyle(node).position !== 'fixed') {
        let clipped = false
        for (let parent = node.parentElement; parent && parent !== document.body; parent = parent.parentElement) {
          if (/(hidden|clip|auto|scroll)/.test(getComputedStyle(parent).overflowX)) { clipped = true; break }
        }
        if (!clipped) wide.push(`${node.tagName.toLowerCase()}.${String(node.className).slice(0, 30)}`)
      }
    }
    const body = getComputedStyle(document.body)
    return {
      overflow: doc.scrollWidth - innerWidth, wide: wide.slice(0, 4),
      text: document.body.innerText,
      font: body.fontFamily, bg: body.backgroundColor,
      pageZoomed: window.visualViewport ? window.visualViewport.scale : 1,
    }
  })
  if (info.overflow > 1) audit.add(where, 'overflow', `horizontal overflow ${info.overflow}px; ${info.wide.join(', ')}`)
  if (info.wide.length) audit.add(where, 'overflow-element', info.wide.join(', '))
  const placeholder = info.text.match(/coming soon|lorem ipsum|not implemented|\bTODO\b|\bTBD\b|placeholder text|under construction/i)
  if (placeholder) audit.add(where, 'placeholder', placeholder[0])
  if (!/Inter/i.test(info.font)) audit.add(where, 'brand', `body font is ${info.font}`)
}
