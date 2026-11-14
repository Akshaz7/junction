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
  clicked: string[] = []
  constructor(readonly page: Page, readonly label: string) {
    page.on('console', (message) => { if (message.type() === 'error') this.consoleErrors.push(message.text()) })
    page.on('pageerror', (error) => this.consoleErrors.push(`pageerror: ${error.message}`))
    page.on('request', (request) => { if (/\/api\//.test(request.url())) this.requests++ })
    page.on('response', (response) => {
      if (/\/api\//.test(response.url()) && response.status() >= 400 && !/\/files\/(elements|text-\d+)\.json$/.test(response.url())) this.badResponses.push(`${response.status()} ${response.request().method()} ${new URL(response.url()).pathname}`)
    })
  }
  add(where: string, kind: string, detail: string) {
    if (!this.findings.some((f) => f.where === where && f.kind === kind && f.detail === detail)) this.findings.push({ where, kind, detail })
  }
  report(testInfo: TestInfo) {
    const text = this.findings.map((f) => `[${f.kind}] ${f.where}: ${f.detail}`).join('\n')
    if (text) console.log(`AUDIT ${this.label}\n${text}`)
    console.log(`AUDIT ${this.label}: clicked ${this.clicked.length}: ${this.clicked.join(' | ')}`)
    return testInfo.attach(`findings-${this.label}`, { body: text || 'none', contentType: 'text/plain' })
  }
  /** Console errors that are not caused by an intentional request failure. */
  unexpectedConsole() {
    return this.consoleErrors.filter((entry) => !/favicon|WebSocket connection|ResizeObserver|net::ERR_ABORTED|Failed to load resource/i.test(entry))
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
export async function collect(page: Page, scope = 'body'): Promise<Item[]> {
  return page.evaluate(([selector, scopeSelector]) => {
    document.querySelectorAll('[data-audit]').forEach((node) => node.removeAttribute('data-audit'))
    const items: { index: number; tag: string; name: string; key: string }[] = []
    const seen: Record<string, number> = {}
    let index = 0
    for (const node of Array.from(document.querySelectorAll<HTMLElement>(scopeSelector).length ? Array.from(document.querySelectorAll<HTMLElement>(scopeSelector)).flatMap((root) => Array.from(root.querySelectorAll<HTMLElement>(selector))) : [])) {
      const style = getComputedStyle(node), rect = node.getBoundingClientRect()
      if (style.visibility === 'hidden' || style.display === 'none' || rect.width < 1 || rect.height < 1) continue
      if (node.closest('[inert],[hidden],[aria-hidden=true]')) continue
      if ((node as HTMLButtonElement).disabled || node.getAttribute('aria-disabled') === 'true') continue
      if (node.closest('.skip-link') || node.matches('.skip-link')) continue
      if (node instanceof SVGElement) continue // evidence boxes are drawing content, covered by the 2D/3D linked tests
      const name = (node.getAttribute('aria-label') || node.textContent || node.getAttribute('title') || node.getAttribute('placeholder') || '').trim().replace(/\s+/g, ' ').slice(0, 60)
      const key = `${node.tagName}.${node.className}`
      seen[key] = (seen[key] || 0) + 1
      if (seen[key] > 3) continue // sample repetitive rows (documents, chats)
      node.setAttribute('data-audit', String(index))
      items.push({ index, tag: node.tagName.toLowerCase(), name, key })
      index++
    }
    return items
  }, [interactive, scope])
}

export async function signature(page: Page) {
  return page.evaluate(() => {
    const states = Array.from(document.querySelectorAll('[aria-pressed],[aria-expanded],[aria-selected],[aria-current],details')).map((node) =>
      `${node.getAttribute('aria-pressed')}${node.getAttribute('aria-expanded')}${node.getAttribute('aria-selected')}${node.getAttribute('aria-current')}${(node as HTMLDetailsElement).open ?? ''}`).join('|')
    const fields = Array.from(document.querySelectorAll<HTMLInputElement>('input,select,textarea')).map((node) => `${node.value}${node.checked ?? ''}`).join('|')
    return [location.hash, document.body.innerText, document.querySelectorAll('*').length, states, fields, document.querySelectorAll('[role=dialog],[role=alertdialog],.document-viewer,.sheet,[popover]:popover-open').length, document.activeElement?.tagName].join('~')
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
    // A control may be visually small if its hit area (e.g. a pseudo-element) reaches 44px. Where an adjacent
    // control blocks the extension, the control must itself be at least 28px (WCAG 2.5.8 spacing exception).
    const reach = (dx: number, dy: number) => {
      const target = document.elementFromPoint(Math.min(Math.max(x + dx, 0), innerWidth - 1), Math.min(Math.max(y + dy, 0), innerHeight - 1))
      if (!target) return false
      if (node.contains(target) || target.contains(node) || (node.closest('label')?.contains(target) ?? false)) return true
      return !!target.closest('button, a[href], summary, select, input, [role=button], [role=tab]') && Math.min(rect.width, rect.height) >= 28 ? true : false
    }
    const hit = (rect.width >= 44 || (reach(-21, 0) && reach(21, 0))) && (rect.height >= 44 || (reach(0, -21) && reach(0, 21)))
    return {
      hit,
      notch: rect.top < 57 || rect.bottom > innerHeight - 32,
      w: Math.round(rect.width), h: Math.round(rect.height), covered,
      offscreen: rect.right < 0 || rect.left > innerWidth + 1 || rect.bottom < 0 || rect.top > innerHeight,
      text: (node.textContent || '').trim().slice(0, 40),
      inProse: !!node.closest('p, li, .answer-text, .markdown') && node.tagName === 'A',
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
      offFont: Array.from(new Set(Array.from(document.querySelectorAll<HTMLElement>('button, input, select, textarea, a, h1, h2, h3, p, label')).filter((n) => n.getClientRects().length && !/Inter/i.test(getComputedStyle(n).fontFamily) && !n.closest('svg, code, pre, .mono')).map((n) => `${n.tagName.toLowerCase()}.${String(n.className).slice(0, 24)}`))).slice(0, 4),
      pageZoomed: window.visualViewport ? window.visualViewport.scale : 1,
    }
  })
  if (info.overflow > 1) audit.add(where, 'overflow', `horizontal overflow ${info.overflow}px; ${info.wide.join(', ')}`)
  if (info.wide.length) audit.add(where, 'overflow-element', info.wide.join(', '))
  const placeholder = info.text.match(/coming soon|lorem ipsum|not implemented|\bTODO\b|\bTBD\b|placeholder text|under construction/i)
  if (placeholder) audit.add(where, 'placeholder', placeholder[0])
  if (info.offFont.length) audit.add(where, 'brand', `non-Inter font on ${info.offFont.join(', ')}`)
  if (!/Inter/i.test(info.font)) audit.add(where, 'brand', `body font is ${info.font}`)
}

/**
 * Click every control inside `scope` once, each from a freshly opened state (`open`), and require
 * that it changes something (route, state, layer, API call) and that any layer it opens can be closed.
 */
export async function crawlScope(page: Page, audit: Audit, name: string, open: () => Promise<void>, scope: string, options: { skip?: RegExp; max?: number } = {}) {
  await open()
  await page.waitForTimeout(800)
  const first = await collect(page, scope)
  let count = 0
  for (const item of first) {
    const where = `${name} > ${item.tag} "${item.name}"`
    if (/delete|remove|discard/i.test(item.name) || options.skip?.test(item.name)) continue
    if (options.max && count >= options.max) break
    await open()
    await page.waitForTimeout(800)
    const current = (await collect(page, scope)).find((entry) => entry.key === item.key && entry.name === item.name)
    if (!current) { audit.add(where, 'unstable', 'control disappeared on reopen'); continue }
    const el = page.locator(`[data-audit="${current.index}"]`)
    const geo = await geometry(el)
    if (!(item.tag === 'a' && geo.inProse) && !geo.hit) audit.add(where, 'touch-target', `${geo.w}x${geo.h}px, hit area under 44px`)
    if (geo.covered) audit.add(where, 'covered', `covered by ${geo.covered}`)
    if (geo.notch) audit.add(where, 'notch', 'control sits under the notch or home bar')
    audit.clicked.push(item.name || item.tag); count++
    const selected = await el.evaluate((node) => node.getAttribute('aria-pressed') === 'true' || node.getAttribute('aria-selected') === 'true' || node.getAttribute('aria-current') !== null)
    const before = await signature(page), requests = audit.requests, bad = audit.badResponses.length, url = page.url()
    try { await el.click({ timeout: 4000 }) } catch (error) { audit.add(where, 'unclickable', String(error).split('\n')[0]); continue }
    await page.waitForTimeout(500)
    if (audit.badResponses.length > bad) audit.add(where, 'bad-response', audit.badResponses.slice(bad).join('; '))
    const file = await page.evaluate(() => document.activeElement instanceof HTMLInputElement && document.activeElement.type === 'file')
    if (before === await signature(page) && audit.requests === requests && page.url() === url && !file && !selected) audit.add(where, 'dead', 'click changed nothing (no route, state, dialog or API call)')
    await closeLayers(page, audit, where)
    await layoutChecks(page, audit, `${where} (after click)`)
  }
}

/** Anything a click opened must be closable: Escape, a Close/Back control, or the nav. */
export async function closeLayers(page: Page, audit: Audit, where: string) {
  const layer = page.locator('[role=dialog]:visible, dialog[open], .document-viewer:visible, [role=alertdialog]:visible')
  if (!await layer.count()) return
  await page.keyboard.press('Escape')
  await page.waitForTimeout(250)
  if (!await layer.count()) return
  const close = page.getByRole('button', { name: /close|back|dismiss|cancel/i }).filter({ visible: true }).first()
  if (await close.count()) { await close.click().catch(() => {}); await page.waitForTimeout(250) }
  if (await layer.count()) audit.add(where, 'dead-end', 'dialog/sheet opened and could not be closed')
}
