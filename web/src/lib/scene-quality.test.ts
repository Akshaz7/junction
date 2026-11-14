import { expect, it } from 'vitest'
import { qualitySummary } from './scene-quality'

it('returns a trimmed single line, or null when absent or blank', () => {
  expect(qualitySummary({ summary: '  Walls match\n the drawing ' })).toBe('Walls match the drawing')
  expect(qualitySummary({ summary: '' })).toBeNull()
  expect(qualitySummary({})).toBeNull()
  expect(qualitySummary(null)).toBeNull()
  expect(qualitySummary(undefined)).toBeNull()
})
