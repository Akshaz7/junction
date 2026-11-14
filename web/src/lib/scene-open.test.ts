import { describe, expect, it } from 'vitest'
import { sceneOpen, sceneOpenCitation } from './scene-open'
import { makeDemoAnswer } from '../mock/handler'

describe('scene.open', () => {
  it('reads 3d and ar, ignores anything else', () => {
    const answer = makeDemoAnswer('How many windows are there?')
    expect(sceneOpen(answer)).toBeNull()
    answer.evidence.scene.open = '3d'; expect(sceneOpen(answer)).toBe('3d')
    answer.evidence.scene.open = 'ar'; expect(sceneOpen(answer)).toBe('ar')
    ;(answer.evidence.scene as { open?: string }).open = 'vr'; expect(sceneOpen(answer)).toBeNull()
  })
  it('picks a citation for the answer doc, or a bare page-1 one when there are none', () => {
    const answer = makeDemoAnswer('How many windows are there?')
    expect(sceneOpenCitation(answer)?.doc_id).toBe(answer.evidence.scene.doc_id || answer.doc_ids[0])
    answer.citations = []
    const bare = sceneOpenCitation(answer)
    expect(bare).toMatchObject({ page: 1, bbox_px: null })
    expect(bare?.doc_id).toBe(answer.evidence.scene.doc_id || answer.doc_ids[0])
  })
})
