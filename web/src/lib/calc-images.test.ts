import { afterEach, expect, it, vi } from 'vitest'
import { calculationImages } from './calc-images'

afterEach(() => vi.unstubAllGlobals())

it('shares one request and decoded image across hundreds of crops, then releases it', async () => {
  const decode = vi.fn().mockResolvedValue(undefined)
  vi.stubGlobal('Image', class { src = ''; decode = decode })
  const createObjectURL = vi.fn().mockReturnValue('blob:page')
  const revokeObjectURL = vi.fn()
  vi.stubGlobal('URL', { createObjectURL, revokeObjectURL })
  const load = vi.fn().mockResolvedValue(new Blob())
  const pool = calculationImages(load)
  const crops = await Promise.all(Array.from({ length: 222 }, () => pool.get('drawing', 1)))
  expect(load).toHaveBeenCalledTimes(1)
  expect(decode).toHaveBeenCalledTimes(1)
  expect(crops.every((image) => image === crops[0])).toBe(true)
  await pool.get('drawing', 2)
  expect(load).toHaveBeenCalledTimes(2)
  pool.clear()
  expect(revokeObjectURL).toHaveBeenCalledTimes(2)
  expect(crops[0].src).toBe('')
  expect(load.mock.calls[0][2].aborted).toBe(true)
})

it('retries failed source pages and aborts pending work when the calculation closes', async () => {
  const load = vi.fn().mockRejectedValueOnce(new Error('Unavailable')).mockImplementation((_doc, _page, signal: AbortSignal) => new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(signal.reason))))
  const pool = calculationImages(load)
  await expect(pool.get('drawing', 1)).rejects.toThrow('Unavailable')
  const pending = pool.get('drawing', 1)
  expect(load).toHaveBeenCalledTimes(2)
  pool.clear()
  await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
})
