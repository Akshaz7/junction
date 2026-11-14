import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { SkillsApi, runTime, scheduleLabel } from './skills'
import { ReportMarkdown } from '../components/automations-screen'

describe('skills and automation API', () => {
  it('runs the chosen skill only against the selected real document and returns its answer', async () => {
    const answer = { answer: { text_md: '**Windows** [1]', abstained: false } }
    const controller = new AbortController()
    const api = new SkillsApi(async (path, init) => {
      expect(path).toBe('/api/skills/a%2Fb/run')
      expect(init?.method).toBe('POST')
      expect(init?.signal).toBe(controller.signal)
      expect(JSON.parse(String(init?.body))).toEqual({ doc_ids: ['ifc_bench__ac20-arc'] })
      return Response.json({ skill_id: 'a/b', answer })
    })
    expect(await api.runSkill('a/b', 'ifc_bench__ac20-arc', controller.signal)).toEqual(answer)
  })
  it('matches the interval scheduler contract and fetches the report as Markdown text', async () => {
    const calls: { path: string; body?: unknown }[] = []
    const api = new SkillsApi(async (path, init) => {
      calls.push({ path: String(path), body: init?.body ? JSON.parse(String(init.body)) : undefined })
      if (String(path).endsWith('/report.md')) return new Response('# Saved report\n\n**Fact** [1]\n', { headers: { 'Content-Type': 'text/markdown' } })
      if (init?.method === 'DELETE') return new Response(null, { status: 204 })
      return Response.json({ id: 'auto' })
    })
    await api.createAutomation(' Daily checks ', ' Count windows ', 'doc', 1440)
    expect(calls[0]).toEqual({ path: '/api/automations', body: { name: 'Daily checks', prompt: 'Count windows', doc_ids: ['doc'], interval_minutes: 1440, enabled: true } })
    expect(await api.report('a/b')).toBe('# Saved report\n\n**Fact** [1]\n')
    expect(calls[1].path).toBe('/api/automations/a%2Fb/report.md')
    await expect(api.deleteSkill('saved')).resolves.toBeUndefined()
  })
  it('preserves server failure messages and never substitutes a demo answer', async () => {
    const api = new SkillsApi(async () => Response.json({ detail: 'engine failed' }, { status: 502 }))
    await expect(api.runSkill('skill', 'doc')).rejects.toThrow('engine failed')
    await expect(new SkillsApi(async () => { throw new TypeError('offline') }).listSkills()).rejects.toThrow('offline')
  })
})

describe('automation reports', () => {
  it('renders report headings, bold answers and sources while keeping HTML inert', () => {
    const html = renderToStaticMarkup(createElement(ReportMarkdown, { markdown: '# Window report\n\n_Ran today_\n\n**Three windows** [1]\n\n## Sources\n\n- doc p.1\n\n<script>alert(1)</script>' }))
    expect(html).toContain('<h3>Window report</h3>')
    expect(html).toContain('<strong>Three windows</strong> [1]')
    expect(html).toContain('<li>doc p.1</li>')
    expect(html).not.toContain('<script>')
    expect(html).toContain('&lt;script&gt;')
  })
  it('labels missing times and uses repeat intervals rather than implying a wall-clock schedule', () => {
    expect(runTime(null)).toBe('Not run yet')
    expect(runTime('invalid')).toBe('Time unavailable')
    expect(scheduleLabel(1440)).toBe('Every day')
    expect(scheduleLabel(15)).toBe('Every 15 minutes')
  })
})
