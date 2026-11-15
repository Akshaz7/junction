// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TellStoaBubble, bubbleSpot } from './tell-stoa-bubble'
import { kindFor } from './taught-kinds'

let host: HTMLDivElement, root: Root
beforeEach(() => { Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true }); host = document.createElement('div'); document.body.append(host); root = createRoot(host) })
afterEach(() => { act(() => root.unmount()); host.remove() })
const show = (el: React.ReactElement) => act(() => root.render(el))
const q = <T extends Element>(sel: string) => host.querySelector(sel) as T
function type(input: HTMLInputElement, value: string) { act(() => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value); input.dispatchEvent(new Event('input', { bubbles: true })) }) }
const key = (el: Element, k: string) => act(() => { el.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true })) })
const props = { box: [100, 100, 200, 160] as [number, number, number, number], view: { x: 0, y: 0, scale: 1 }, stage: { width: 800, height: 600 }, busy: false }

describe('kindFor', () => {
  it('maps common words to standard kinds and leaves the rest as the user\'s own', () => {
    expect(kindFor('Door')?.id).toBe('door')
    expect(kindFor(' supply air terminal ')?.id).toBe('terminal')
    expect(kindFor('D-swing')).toBeNull()
  })
})

describe('bubbleSpot', () => {
  it('sits under the box, follows zoom, flips above near the bottom and clamps to the stage', () => {
    expect(bubbleSpot(props.box, props.view, props.stage).y).toBe(170)
    expect(bubbleSpot(props.box, { x: 0, y: 0, scale: 2 }, props.stage).x).toBe(200)
    expect(bubbleSpot([100, 500, 200, 560], props.view, props.stage).y).toBeLessThan(500)
    expect(bubbleSpot([790, 100, 800, 160], props.view, props.stage).x).toBeLessThanOrEqual(800 - 196 - 8)
  })
})

describe('TellStoaBubble', () => {
  it('saves a typed word that maps to a standard kind, on Enter', () => {
    const onSave = vi.fn()
    show(<TellStoaBubble {...props} onSave={onSave} onClose={() => {}} />)
    const input = q<HTMLInputElement>('input')
    expect(input.placeholder).toMatch(/Mark this as/)
    expect(document.activeElement).toBe(input)
    type(input, 'door')
    expect(host.querySelector('.tell-stoa-status, .tell-stoa-chip')).toBeNull()
    key(input, 'Enter')
    expect(onSave).toHaveBeenCalledWith('door', 'door')
  })
  it('shows no chips or kind line, sends free text with no kind, and Escape closes', () => {
    const onSave = vi.fn(), onClose = vi.fn()
    show(<TellStoaBubble {...props} onSave={onSave} onClose={onClose} />)
    expect(q<HTMLButtonElement>('.tell-stoa-send').disabled).toBe(true)
    expect(host.querySelector('.tell-stoa-chips, .tell-stoa-chip')).toBeNull()
    type(q('input'), 'D-swing')
    expect(host.querySelector('.tell-stoa-status')).toBeNull()
    act(() => q<HTMLButtonElement>('.tell-stoa-send').click())
    expect(onSave).toHaveBeenLastCalledWith('D-swing', null)
    expect(q('.tell-stoa-pill .tell-stoa-logo')).toBeTruthy()
    expect(q('[role=tooltip]').textContent).toMatch(/counts it as that item/)
    key(q('input'), 'Escape')
    expect(onClose).toHaveBeenCalled()
  })
  it('edit mode starts with the saved name and offers delete', () => {
    const onDelete = vi.fn()
    show(<TellStoaBubble {...props} initial={{ name: 'Door', kind: 'door' }} onSave={() => {}} onDelete={onDelete} onClose={() => {}} />)
    expect(q<HTMLInputElement>('input').value).toBe('Door')
    act(() => q<HTMLButtonElement>('.tell-stoa-delete').click())
    expect(onDelete).toHaveBeenCalled()
  })
})
