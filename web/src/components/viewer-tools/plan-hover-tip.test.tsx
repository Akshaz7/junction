// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { PlanHoverTip, tipSpot } from './plan-hover-tip'

let host: HTMLDivElement, root: Root
beforeEach(() => { Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true }); host = document.createElement('div'); document.body.append(host); root = createRoot(host) })
afterEach(() => { act(() => root.unmount()); host.remove() })
const show = (el: React.ReactElement) => act(() => root.render(el))
const tip = () => host.querySelector('[data-testid="plan-hover-tip"]') as HTMLDivElement | null

describe('PlanHoverTip', () => {
  it('renders a tooltip 14px from the cursor', () => {
    show(<PlanHoverTip text="Wall · 10.57 m long · 0.27 m thick" x={100} y={50} containerWidth={800} containerHeight={600} />)
    const el = tip()!
    expect(el.getAttribute('role')).toBe('tooltip')
    expect(el.textContent).toBe('Wall · 10.57 m long · 0.27 m thick')
    expect(el.style.left).toBe('114px')
    expect(el.style.top).toBe('64px')
    expect(el.hasAttribute('data-flip-x')).toBe(false)
  })
  it('flips left and up near the right/bottom edges', () => {
    show(<PlanHoverTip text="Door · 0.96 m wide" x={790} y={590} containerWidth={800} containerHeight={600} />)
    const el = tip()!
    expect(el.dataset.flipX).toBe('true')
    expect(el.dataset.flipY).toBe('true')
    expect(parseFloat(el.style.left)).toBeLessThan(790)
    expect(parseFloat(el.style.top)).toBeLessThan(590)
    expect(tipSpot(790, 590, 120, 26, 800, 600)).toEqual({ left: 656, top: 550, flipX: true, flipY: true })
  })
  it('hides on null text', () => {
    show(<PlanHoverTip text={null} x={10} y={10} containerWidth={800} containerHeight={600} />)
    expect(tip()).toBeNull()
  })
})
