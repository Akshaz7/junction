import { afterEach, describe, expect, it, vi } from 'vitest'
import { createRetryTransport, retryMessage, subscribeApiRetry, WorkspaceApi } from './api'

afterEach(() => { vi.useRealTimers() })
const limited = (retryAfter = '2') => Response.json({ detail: 'rate limit exceeded' }, { status: 429, headers: { 'Retry-After': retryAfter } })

describe('HTTP recovery', () => {
  it('counts down Retry-After and retries a rejected POST with the original payload', async () => {
    vi.useFakeTimers()
    const transport = vi.fn<typeof fetch>().mockResolvedValueOnce(limited()).mockResolvedValueOnce(Response.json({ id: 'saved' }))
    const status = vi.fn()
    const stop = subscribeApiRetry(status)
    const result = new WorkspaceApi('real', transport).createChat(['doc'], 'Question')
    await vi.advanceTimersByTimeAsync(0)
    expect(status).toHaveBeenLastCalledWith('Too many requests, retrying in 2s')
    await vi.advanceTimersByTimeAsync(1_000)
    expect(status).toHaveBeenLastCalledWith('Too many requests, retrying in 1s')
    expect(transport).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1_000)
    expect(await result).toBe('saved')
    expect(transport.mock.calls[1]).toEqual(transport.mock.calls[0])
    expect(status).toHaveBeenLastCalledWith('')
    stop()
  })

  it('respects date Retry-After headers and stops after two retries without raw server text', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-11-14T12:00:00Z'))
    const transport = vi.fn<typeof fetch>().mockImplementation(async () => limited('Sat, 14 Nov 2026 12:00:03 GMT'))
    const request = createRetryTransport(transport)('/api/docs')
    const rejected = expect(request).rejects.toThrow('Too many requests. Please try again shortly.')
    await vi.advanceTimersByTimeAsync(2_999)
    expect(transport).toHaveBeenCalledTimes(1)
    expect(retryMessage()).toBe('Too many requests, retrying in 1s')
    await vi.advanceTimersByTimeAsync(1)
    await vi.runAllTimersAsync()
    await rejected
    expect(transport).toHaveBeenCalledTimes(3)
    expect(retryMessage()).toBe('')
  })

  it('cancels a pending retry immediately and removes its countdown', async () => {
    vi.useFakeTimers()
    const controller = new AbortController()
    const transport = vi.fn<typeof fetch>().mockImplementation(async () => limited('60'))
    const result = createRetryTransport(transport)('/api/docs', { signal: controller.signal })
    const rejected = expect(result).rejects.toMatchObject({ name: 'AbortError' })
    await vi.advanceTimersByTimeAsync(0)
    controller.abort()
    await rejected
    await vi.advanceTimersByTimeAsync(60_000)
    expect(transport).toHaveBeenCalledTimes(1)
    expect(retryMessage()).toBe('')
    expect(vi.getTimerCount()).toBe(0)
  })

  it.each([502, 503])('retries GET %s twice at one-second intervals and recovers', async (status) => {
    vi.useFakeTimers()
    const transport = vi.fn<typeof fetch>()
      .mockImplementationOnce(async () => new Response('', { status }))
      .mockImplementationOnce(async () => new Response('', { status }))
      .mockResolvedValueOnce(Response.json({ id: 'saved', messages: [] }))
    const result = new WorkspaceApi('real', transport).getChat('saved')
    await vi.advanceTimersByTimeAsync(999)
    expect(transport).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1_000)
    expect(transport).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(1)
    expect(await result).toEqual({ id: 'saved', messages: [] })
    expect(transport).toHaveBeenCalledTimes(3)
  })

  it('limits restart retries and never replays POSTs after a 503', async () => {
    vi.useFakeTimers()
    const transport = vi.fn<typeof fetch>().mockImplementation(async () => Response.json({ detail: 'Restarting' }, { status: 503 }))
    const api = new WorkspaceApi('real', transport)
    const read = api.getChat('saved')
    const rejected = expect(read).rejects.toThrow('Restarting')
    await vi.runAllTimersAsync()
    await rejected
    expect(transport).toHaveBeenCalledTimes(3)
    await expect(api.createChat([], 'Question')).rejects.toThrow('Restarting')
    expect(transport).toHaveBeenCalledTimes(4)
  })
})
