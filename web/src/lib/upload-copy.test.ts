import { describe, expect, it } from 'vitest'
import { friendlyFailure, friendlyStage } from './upload-client'

describe('upload copy', () => {
  it('maps internal stages to plain names', () => {
    expect(friendlyStage('usdz')).toBe('Preparing AR model')
    expect(friendlyStage('ifc scene')).toBe('Building 3D')
    expect(friendlyStage('planmap_vlm')).toBe('Reading drawing')
    expect(friendlyStage(undefined)).toBe('')
  })
  it('hides raw errors behind details', () => {
    expect(friendlyFailure('RuntimeError: usdz conversion produced no geometry')).toEqual({ message: 'This file has no 3D geometry we can convert.', raw: 'RuntimeError: usdz conversion produced no geometry' })
    expect(friendlyFailure('RuntimeError: boom').message).toMatch(/could not process/)
    expect(friendlyFailure('The file is too large.')).toEqual({ message: 'The file is too large.', raw: '' })
  })
})
