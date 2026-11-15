// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it } from 'vitest'
import { ThinkingRow, thinkingLabel } from './thinking-row'

let host: HTMLDivElement
let root: Root
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
})
afterEach(async () => { await act(async () => root.unmount()); host.remove() })

it('shows one live disclosure, splits the verb and keeps history collapsed', async () => {
  await act(async () => root.render(<ThinkingRow active statuses={['Thinking…', 'Searching: EI 60 stair core']} />))
  expect(host.querySelectorAll('summary')).toHaveLength(1)
  expect(host.querySelector('details')!.open).toBe(false)
  expect(host.querySelector('.thinking-verb')!.textContent).toBe('Searching:')
  expect(host.querySelector('[role="status"]')!.textContent).toBe('Searching: EI 60 stair core')
  expect(host.querySelector('.thinking-mark img')!.getAttribute('src')).toBe('/brand/stoa-logo.svg')
  expect(thinkingLabel('Counting doors')).toBe('Counting: doors')
  expect(thinkingLabel('')).toBe('Thinking…')
})

it('falls back to the SVG mark when the brand file fails', async () => {
  await act(async () => root.render(<ThinkingRow active />))
  await act(async () => host.querySelector('img')!.dispatchEvent(new Event('error')))
  expect(host.querySelector('.thinking-mark svg')).not.toBeNull()
  expect(host.querySelector('.thinking-mark')!.textContent).toBe('')
})

it('shows the completed thought process with the same logo and no live status', async () => {
  await act(async () => root.render(<ThinkingRow traces={[{ step: 'read', detail: 'Read the drawing', ms: 0, model: null, cost_usd: 0 }]} />))
  expect(host.querySelector('summary')!.textContent).toBe('Show thought process')
  expect(host.querySelector('details')!.open).toBe(false)
  expect(host.querySelector('[role="status"]')).toBeNull()
  expect(host.querySelector('.thinking-mark img')).not.toBeNull()
  expect(host.querySelector('.status-trail')!.textContent).toBe('Read the drawing')
})
