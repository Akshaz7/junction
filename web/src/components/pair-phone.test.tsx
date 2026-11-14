import { describe, expect, it } from 'vitest'
import { openChatId } from './pair-phone'

describe('openChatId', () => {
  it('reads the chat from the hash', () => {
    expect(openChatId('#/chat?chat=abc-123')).toBe('abc-123')
    expect(openChatId('#/chat')).toBeNull()
    expect(openChatId('')).toBeNull()
  })
})
