import { describe, expect, it } from 'vitest'
import { needsDocument } from './needs-document'

describe('needsDocument', () => {
  it.each([
    'How many windows are there?',
    'What is the area of this room?',
    'Where is the stair core on level 2?',
    'What does this drawing say about the doors?',
    'Count the doors on the plan',
    'how big is the building',
  ])('blocks "%s" with no document', (q) => expect(needsDocument(q)).toBe(true))
  it.each([
    'what can you do?',
    'How do I upload files?',
    'who are you',
    'Hello',
    '',
  ])('lets general question "%s" through', (q) => expect(needsDocument(q)).toBe(false))
})
