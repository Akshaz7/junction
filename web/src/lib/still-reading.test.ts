import { describe, expect, it, vi } from 'vitest'
import { makeDemoAnswer } from '../mock/handler'
import { askUntilReadable, isStillProcessing } from './still-reading'

const busy = () => { const a = makeDemoAnswer('q'); a.answer.text_md = 'This document is still being processed, so there is nothing to answer from yet. Try again in a moment.'; return a }
const real = () => makeDemoAnswer('How many windows are there?')

describe('askUntilReadable', () => {
  it('retries until the real answer arrives', async () => {
    const ask = vi.fn().mockResolvedValueOnce(busy()).mockResolvedValueOnce(busy()).mockResolvedValueOnce(real())
    const onWait = vi.fn()
    const result = await askUntilReadable(ask, { onWait, sleep: async () => {} })
    expect(ask).toHaveBeenCalledTimes(3)
    expect(onWait).toHaveBeenCalledTimes(2)
    expect(isStillProcessing(result)).toBe(false)
  })
  it('gives up after the limit and returns the last answer', async () => {
    const ask = vi.fn().mockResolvedValue(busy())
    const result = await askUntilReadable(ask, { sleep: async () => {}, intervalMs: 4000, maxMs: 90_000 })
    expect(ask).toHaveBeenCalledTimes(1 + 22)
    expect(isStillProcessing(result)).toBe(true)
  })
  it('stops when cancelled and does not retry a normal answer', async () => {
    const ask = vi.fn().mockResolvedValue(real())
    await askUntilReadable(ask, { sleep: async () => {} })
    expect(ask).toHaveBeenCalledTimes(1)
    const again = vi.fn().mockResolvedValue(busy())
    await askUntilReadable(again, { sleep: async () => {}, cancelled: () => true })
    expect(again).toHaveBeenCalledTimes(1)
  })
})
