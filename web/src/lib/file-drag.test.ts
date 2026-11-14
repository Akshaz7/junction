import { describe, expect, it } from 'vitest'
import { isFileDrag, pickDroppedFile } from './file-drag'

describe('file drag helpers', () => {
  it('detects file drags only', () => {
    expect(isFileDrag({ types: ['Files'] })).toBe(true)
    expect(isFileDrag({ types: ['text/plain', 'Files'] })).toBe(true)
    expect(isFileDrag({ types: ['text/plain'] })).toBe(false)
    expect(isFileDrag({ types: [] })).toBe(false)
    expect(isFileDrag(null)).toBe(false)
  })
  it('accepts one supported file', () => {
    const file = new File(['x'], 'Plan.PNG')
    expect(pickDroppedFile([file])).toEqual({ file })
    expect(pickDroppedFile([])).toBeNull()
  })
  it('rejects several files, wrong types and empty files', () => {
    const a = new File(['x'], 'a.png')
    expect(pickDroppedFile([a, a])).toMatchObject({ error: expect.stringContaining('one drawing') })
    expect(pickDroppedFile([new File(['x'], 'notes.txt')])).toMatchObject({ error: expect.stringContaining('PDF') })
    expect(pickDroppedFile([new File([], 'a.pdf')])).toMatchObject({ error: expect.stringContaining('empty') })
  })
})
