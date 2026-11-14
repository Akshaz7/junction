// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it } from 'vitest'
import { SheetCompare, type SheetChange } from './sheet-compare'
import { buildExportHtml } from '../lib/sheet-export'

let host: HTMLDivElement
let root: Root
const changes: SheetChange[] = [
  { id: 'a', n: 1, kind: 'added', bbox: [100, 100, 300, 200], text: 'Note added near the left of the sheet' },
  { id: 'b', n: 2, kind: 'removed', bbox: null, text: 'Drawing content removed' },
  { id: 'c', n: 3, kind: 'edited', bbox: [500, 400, 520, 410], text: 'Small linework edited', small: true },
]
const props = { prev: { label: 'Version 1', src: '/p1.png' }, curr: { label: 'Version 2', src: '/p2.png' }, size: { w: 1000, h: 800 }, changes }

beforeEach(() => { Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true }); host = document.createElement('div'); document.body.append(host); root = createRoot(host) })
afterEach(async () => { await act(async () => root.unmount()); host.remove() })

it('seam slider answers the keyboard and reports its value', async () => {
  await act(async () => root.render(<SheetCompare {...props} initialMode="Wipe" />))
  const slider = host.querySelector<HTMLElement>('[role=slider]')!
  expect(slider.getAttribute('aria-label')).toBe('Wipe position')
  await act(async () => { slider.dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', bubbles: true })) })
  expect(slider.getAttribute('aria-valuenow')).toBe('0')
  await act(async () => { slider.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', shiftKey: true, bubbles: true })) })
  expect(slider.getAttribute('aria-valuenow')).toBe('10')
})

it('draws one numbered box per placed change and one card per change; missing boxes still get a card', async () => {
  await act(async () => root.render(<SheetCompare {...props} />))
  expect(host.querySelectorAll('.sc-box')).toHaveLength(2)
  expect(host.querySelectorAll('article.sc-card')).toHaveLength(3)
  expect(host.querySelector('.cmp-small')).not.toBeNull()
})

it('says so when a sheet image is missing instead of showing an empty canvas', async () => {
  await act(async () => root.render(<SheetCompare {...props} prev={{ label: 'Version 1', src: null }} />))
  expect(host.querySelector('.sc-missing')?.textContent).toMatch(/Version 1/)
})

it('export page lists every change with its number and text, escaped', () => {
  const html = buildExportHtml('Plan <A>', 'Version 1', 'Version 2', [{ n: 1, kind: 'added', text: 'Note "x" & <b>', before: null, after: null }], new Date('2026-11-14'))
  expect(html).toContain('Plan &lt;A&gt;')
  expect(html).toContain('&amp;')
  expect(html).not.toContain('<b>')
})
