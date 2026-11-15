import { describe, expect, it } from 'vitest'
import { readOnceLabel, readSeconds } from './read-once-chip'

describe('read once label', () => {
  it('formats cost and duration', () => expect(readOnceLabel(0.01234, readSeconds([{ s: 1.2 }, { s: 3 }]))).toBe('Read once: $0.0123 · 4.2s'))
  it('shows nothing without a recorded cost', () => { expect(readOnceLabel(null, 3)).toBeNull(); expect(readOnceLabel(undefined, null)).toBeNull() })
  it('shows cost alone without stages', () => expect(readOnceLabel(0, readSeconds([]))).toBe('Read once: $0.0000'))
})
