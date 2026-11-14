import type { Answer } from './types'

export interface Skill { id: string; name: string; prompt: string; description: string; builtin: boolean }
export interface Automation {
  id: string; name: string; prompt: string; doc_ids: string[]; interval_minutes: number; enabled: boolean
  last_run_at: string | null; next_run_at: string | null
  last_report: { report_id: string; ran_at: string; ok: boolean; markdown: string; answer: Answer | null } | null
}
export const schedules = [{ minutes: 60, label: 'Every hour' }, { minutes: 1440, label: 'Every day' }, { minutes: 10080, label: 'Every week' }] as const
export function scheduleLabel(minutes: number) { return schedules.find((schedule) => schedule.minutes === minutes)?.label ?? `Every ${minutes} minutes` }
export function runTime(value: string | null) {
  if (!value) return 'Not run yet'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? 'Time unavailable' : date.toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}
export class SkillsApi {
  constructor(private transport: typeof fetch = (...args) => fetch(...args)) {}
  private async request<T>(path: string, method = 'GET', body?: unknown, signal?: AbortSignal): Promise<T> {
    const response = await this.transport(path, { method, signal, ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }) })
    if (!response.ok) {
      let detail = `The request could not be completed (${response.status}). Please try again.`
      try { const payload = await response.json(); if (typeof payload.detail === 'string') detail = payload.detail } catch { /* A proxy may return plain text. */ }
      throw new Error(detail)
    }
    if (response.status === 204) return undefined as T
    if (path.endsWith('/report.md')) return await response.text() as T
    return response.json() as Promise<T>
  }
  async listSkills(signal?: AbortSignal) { return (await this.request<{ skills: Skill[] }>('/api/skills', 'GET', undefined, signal)).skills }
  createSkill(name: string, prompt: string, signal?: AbortSignal) { return this.request<Skill>('/api/skills', 'POST', { name: name.trim(), prompt: prompt.trim() }, signal) }
  deleteSkill(id: string, signal?: AbortSignal) { return this.request<void>(`/api/skills/${encodeURIComponent(id)}`, 'DELETE', undefined, signal) }
  async runSkill(id: string, docId: string, signal?: AbortSignal) { return (await this.request<{ answer: Answer }>(`/api/skills/${encodeURIComponent(id)}/run`, 'POST', { doc_ids: [docId] }, signal)).answer }
  async listAutomations(signal?: AbortSignal) { return (await this.request<{ automations: Automation[] }>('/api/automations', 'GET', undefined, signal)).automations }
  createAutomation(name: string, prompt: string, docId: string, intervalMinutes: number, signal?: AbortSignal) { return this.request<Automation>('/api/automations', 'POST', { name: name.trim(), prompt: prompt.trim(), doc_ids: [docId], interval_minutes: intervalMinutes, enabled: true }, signal) }
  getAutomation(id: string, signal?: AbortSignal) { return this.request<Automation>(`/api/automations/${encodeURIComponent(id)}`, 'GET', undefined, signal) }
  deleteAutomation(id: string, signal?: AbortSignal) { return this.request<void>(`/api/automations/${encodeURIComponent(id)}`, 'DELETE', undefined, signal) }
  runAutomation(id: string, signal?: AbortSignal) { return this.request<Automation>(`/api/automations/${encodeURIComponent(id)}/run`, 'POST', undefined, signal) }
  report(id: string, signal?: AbortSignal) { return this.request<string>(`/api/automations/${encodeURIComponent(id)}/report.md`, 'GET', undefined, signal) }
}
export const skillsApi = new SkillsApi()

export function downloadReport(name: string, markdown: string) {
  const url = URL.createObjectURL(new Blob([markdown], { type: 'text/markdown;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url; link.download = `${name.replace(/[^a-z0-9_-]+/gi, '-').replace(/^-|-$/g, '') || 'report'}.md`
  document.body.append(link); link.click(); link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
