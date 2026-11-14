import { devices, expect, test, type Page } from '@playwright/test'
import { Audit, closeLayers, collect, geometry, installSafeAreas, layoutChecks, openRoute, routes, signature } from './audit-phone'

/**
 * Phone button audit: every route reached through the bottom tabs + More, every visible
 * control clicked, and each must lead somewhere (route, dialog, state change or API call).
 * Run on iPhone 15 Pro Max emulation and a plain 390x844 viewport.
 */
const { defaultBrowserType: _ignored, ...iphone } = devices['iPhone 15 Pro Max']
const configs = [
  { label: 'iphone15promax', use: { ...iphone, viewport: { width: 430, height: 932 } } },
  { label: 'viewport390', use: { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true } },
]

const destructive = /delete|remove|discard|clear/i
const skipName = /show on table|^hologram|download|open source|share$/i

for (const config of configs) {
  test.describe(`phone audit ${config.label}`, () => {
    test.use(config.use)
    test.beforeEach(async ({ page }) => { await installSafeAreas(page) })

    test('every route is reachable through the bottom tabs and More, and passes layout checks', async ({ page }, testInfo) => {
      test.setTimeout(120_000)
      const audit = new Audit(page, `${config.label}-nav`)
      await openRoute(page, 'overview')
      const nav = page.getByRole('navigation', { name: 'Mobile navigation', exact: true })
      await expect(nav).toBeVisible()
      const tabs: Record<string, string> = { Overview: 'overview', Chat: 'chat', Changes: 'changes', Data: 'data' }
      const more: Record<string, string> = { Compare: 'compare', Library: 'library', Tools: 'tools', Accuracy: 'accuracy' }
      for (const [name, route] of Object.entries(tabs)) {
        await nav.getByRole('link', { name, exact: true }).click()
        await expect(page).toHaveURL(new RegExp(`#/${route}`))
        await page.waitForLoadState('networkidle', { timeout: 6000 }).catch(() => {})
        await layoutChecks(page, audit, `${route}`)
        await navChecks(page, audit, route)
      }
      for (const [name, route] of Object.entries(more)) {
        await nav.getByRole('button', { name: 'More pages' }).or(nav.getByText('More', { exact: true })).first().click()
        await nav.getByRole('link', { name, exact: true }).click()
        await expect(page).toHaveURL(new RegExp(`#/${route}`))
        await page.waitForLoadState('networkidle', { timeout: 6000 }).catch(() => {})
        await layoutChecks(page, audit, `${route}`)
        await navChecks(page, audit, route)
      }
      await audit.report(testInfo)
      expect.soft(audit.unexpectedConsole(), 'console errors').toEqual([])
      expect.soft(audit.badResponses, 'failed API calls').toEqual([])
      expect(audit.findings).toEqual([])
    })

    for (const route of routes) {
      test(`crawl ${route}: every control leads somewhere`, async ({ page }, testInfo) => {
        test.setTimeout(600_000)
        const audit = new Audit(page, `${config.label}-${route}`)
        await openRoute(page, route)
        await layoutChecks(page, audit, route)
        const first = await collect(page)
        for (const item of first) {
          const where = `${route} > ${item.tag} "${item.name}"`
          if (destructive.test(item.name) || skipName.test(item.name)) continue
          await openRoute(page, route)
          const items = await collect(page)
          const current = items.find((entry) => entry.key === item.key && entry.name === item.name && entry.index >= 0)
          if (!current) { audit.add(where, 'unstable', 'control disappeared on reload'); continue }
          const el = page.locator(`[data-audit="${current.index}"]`)
          const geo = await geometry(el)
          const tap = item.tag === 'a' && geo.inProse ? 0 : 44
          if (tap && !geo.hit) audit.add(where, 'touch-target', `${geo.w}x${geo.h}px, hit area under 44px`)
          if (geo.notch) audit.add(where, 'notch', 'control sits under the notch or home bar')
          if (geo.covered) audit.add(where, 'covered', `covered by ${geo.covered}`)
          audit.clicked.push(item.name || item.tag)
          const before = await signature(page)
          const requestsBefore = audit.requests
          const badBefore = audit.badResponses.length
          const urlBefore = page.url()
          try { await el.click({ timeout: 4000, trial: false }) } catch (error) { audit.add(where, 'unclickable', String(error).split('\n')[0]); continue }
          await page.waitForTimeout(450)
          if (audit.badResponses.length > badBefore) audit.add(where, 'bad-response', audit.badResponses.slice(badBefore).join('; '))
          const after = await signature(page)
          const moved = page.url() !== urlBefore
          if (before === after && audit.requests === requestsBefore && !moved && !(await isFile(page))) audit.add(where, 'dead', 'click changed nothing (no route, state, dialog or API call)')
          await closeLayers(page, audit, where)
          await layoutChecks(page, audit, `${where} (after click)`)
        }
        await audit.report(testInfo)
        expect.soft(audit.unexpectedConsole(), 'console errors').toEqual([])
        expect(audit.findings).toEqual([])
      })
    }
  })
}

async function isFile(page: Page) {
  return page.evaluate(() => document.activeElement instanceof HTMLInputElement && document.activeElement.type === 'file')
}

async function navChecks(page: Page, audit: Audit, route: string) {
  const geo = await page.evaluate(() => {
    const nav = document.querySelector('.mobile-navigation')!.getBoundingClientRect()
    const main = document.querySelector('main')!
    const lastBottom = Array.from(main.querySelectorAll<HTMLElement>('*')).reduce((max, node) => {
      const rect = node.getBoundingClientRect()
      return rect.height && rect.top < innerHeight ? Math.max(max, rect.bottom) : max
    }, 0)
    const links = Array.from(document.querySelectorAll<HTMLElement>('.mobile-navigation a, .mobile-navigation summary')).map((node) => { const r = node.getBoundingClientRect(); return { name: node.textContent?.trim(), w: r.width, h: r.height } })
    const tabbar = getComputedStyle(document.querySelector('.mobile-navigation')!)
    return { navTop: nav.top, navBottom: nav.bottom, vh: innerHeight, links, lastBottom, safe: getComputedStyle(document.documentElement).getPropertyValue('--app-safe-bottom'), padding: tabbar.paddingBottom }
  })
  if (geo.navBottom > geo.vh + 1) audit.add(route, 'nav', `bottom bar extends below the viewport (${geo.navBottom} > ${geo.vh})`)
  for (const link of geo.links) if (link.h < 44 || link.w < 44) audit.add(route, 'touch-target', `nav "${link.name}" ${Math.round(link.w)}x${Math.round(link.h)}`)
  const topbar = await page.locator('.topbar').boundingBox()
  if (topbar && topbar.y < 0) audit.add(route, 'notch', 'topbar starts above the viewport')
}
