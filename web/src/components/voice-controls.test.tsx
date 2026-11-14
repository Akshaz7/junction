// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

const rec = vi.hoisted(() => ({ cb: null as null | { onState: (s: string) => void; onError: (m: string) => void; onText: (t: string) => void; onInterim?: (t: string) => void } }))
vi.mock('../lib/voice', async (original) => ({ ...(await original<typeof import('../lib/voice')>()),
  voiceInputSupported: () => (globalThis as { __voice?: boolean }).__voice !== false,
  recordQuestion: (cb: NonNullable<typeof rec.cb>) => { rec.cb = cb; cb.onState('requesting'); return { stop() {}, cancel() {} } } }))
import { MicButton } from './voice-controls'

let host: HTMLDivElement
let root: Root
beforeEach(() => { Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true, __voice: true }); host = document.createElement('div'); document.body.append(host); root = createRoot(host) })
afterEach(async () => { await act(async () => root.unmount()); host.remove() })

it('shows a pulsing listening state, then an error hint when the mic is denied', async () => {
  await act(async () => root.render(<MicButton onText={() => {}} />))
  await act(async () => host.querySelector<HTMLButtonElement>('[aria-label="Speak a question"]')!.click())
  expect(host.textContent).toContain('Allow microphone access')
  await act(async () => rec.cb!.onState('recording'))
  expect(host.querySelector('.voice-button.listening')).not.toBeNull()
  expect(host.querySelector('[role="status"]')!.textContent).toContain('Listening…')
  await act(async () => { rec.cb!.onError('Microphone access was denied. Allow it in your browser settings, or type your question.'); rec.cb!.onState('idle') })
  expect(host.querySelector('.voice-button.listening')).toBeNull()
  expect(host.querySelector('[role="status"]')!.textContent).toContain('Microphone access was denied')
  expect(host.querySelector('[role="status"]')!.getAttribute('data-tone')).toBe('error')
})

it('is not rendered when the browser can neither record nor recognise speech', async () => {
  Object.assign(globalThis, { __voice: false })
  await act(async () => root.render(<MicButton onText={() => {}} />))
  expect(host.querySelector('[aria-label="Speak a question"]')).toBeNull()
})
