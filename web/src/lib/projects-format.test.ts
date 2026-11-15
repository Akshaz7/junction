import { describe, expect, it } from 'vitest'
import { area, count, fileCount, relativeTime, thumbUrl, typeTag } from './projects-format'
import { projectChatHref, projectHref, queueUploads, takeUploads } from './projects-api'

describe('projects format', () => {
  it('uses the supported page-image endpoint for legacy project thumbnails', () => {
    expect(thumbUrl({ doc_id: 'any-file', thumb_url: '/api/docs/any-file/pages/1.png' })).toBe('/api/docs/any-file/pages/1/image')
    expect(thumbUrl({ doc_id: 'another', thumb_url: '/api/docs/another/pages/12.png' })).toBe('/api/docs/another/pages/12/image')
    expect(thumbUrl({ doc_id: 'a b' })).toBe('/api/docs/a%20b/files/page-1.thumb.png')
    expect(thumbUrl({ doc_id: 'x', thumb_url: 'https://images.example.com/page.png' })).toBe('https://images.example.com/page.png')
  })
  it('counts files in plain words', () => {
    expect(fileCount(0)).toBe('0 files')
    expect(fileCount(1)).toBe('1 file')
    expect(fileCount(4)).toBe('4 files')
  })
  it('shows a dash when a total is unknown instead of a made-up number', () => {
    expect(count(null)).toBe('–')
    expect(area(undefined)).toBe('–')
    expect(area(212.4)).toBe('212 m²')
  })
  it('names the file type from the format', () => {
    expect(typeTag({ kind: 'ifc', formats: ['ifc'] })).toBe('IFC')
    expect(typeTag({ kind: 'raster', formats: ['png'] })).toBe('PNG')
  })
  it('gives relative times and nothing for a bad date', () => {
    expect(relativeTime(new Date(Date.now() - 3 * 86400_000).toISOString())).toMatch(/3 days ago/)
    expect(relativeTime('not a date')).toBe('')
  })
})

describe('project links', () => {
  it('builds project and chat links without internal ids in labels', () => {
    expect(projectHref('a b')).toBe('#/projects?id=a%20b')
    expect(projectHref('p1', 'files')).toBe('#/projects?id=p1&tab=files')
    expect(projectChatHref('p1')).toBe('#/chat?project=p1')
    expect(projectChatHref('p1', undefined, 'How many doors?')).toContain('send=1')
  })
  it('hands queued uploads over exactly once', () => {
    const file = new File(['x'], 'plan.png')
    queueUploads('p1', [file])
    expect(takeUploads('p1')).toEqual([file])
    expect(takeUploads('p1')).toEqual([])
  })
})
