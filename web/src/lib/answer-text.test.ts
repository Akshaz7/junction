import { describe, expect, it } from 'vitest'
import { humanizeIds, isOneLine, parseBlocks, plainQuote } from './answer-text'

describe('answer text helpers', () => {
  it('never shows internal ids', () => {
    expect(humanizeIds('See room-004 and door-012.')).toBe('See Room 4 and Door 12.')
    expect(humanizeIds('room-004 is large', { 'room-004': 'Kitchen' })).toBe('Kitchen is large')
    expect(humanizeIds('page-2 stays')).toBe('page-2 stays')
  })
  it('strips markdown markers from quotes', () => {
    expect(plainQuote('**Delay** of `5` days')).toBe('Delay of 5 days')
    expect(plainQuote('a ** b')).toBe('a  b')
  })
  it('parses pipe tables between text', () => {
    const blocks = parseBlocks('Intro\n\n| Room | Area |\n|---|---|\n| Kitchen | 12 |\n| Hall | 5 |\n\nAfter')
    expect(blocks.map((b) => b.type)).toEqual(['text', 'table', 'text'])
    expect(blocks[1]).toEqual({ type: 'table', header: ['Room', 'Area'], rows: [['Kitchen', '12'], ['Hall', '5']] })
  })
  it('detects one-line answers', () => {
    expect(isOneLine('**11 windows** [1]')).toBe(true)
    expect(isOneLine('a\n\nb')).toBe(false)
    expect(isOneLine('| a |\n|---|')).toBe(false)
  })
})
