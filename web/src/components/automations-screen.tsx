import { useEffect, useRef, useState } from 'react'
import { Clock3, Download, Play, Trash2 } from 'lucide-react'
import { downloadReport, runTime, scheduleLabel, schedules, skillsApi, type Automation } from '../lib/skills'
import type { Document } from '../lib/types'
import { Button } from './ui'
import { DrawingPicker, drawingDocuments } from './skills-screen'
import './automations-screen.css'

/** Small safe Markdown renderer: API reports are text, never trusted HTML. */
export function ReportMarkdown({ markdown }: { markdown: string }) {
  function inline(text: string) { return text.split(/(\*\*[^*]+\*\*|_[^_]+_)/g).map((part, index) => part.startsWith('**') ? <strong key={index}>{part.slice(2, -2)}</strong> : part.startsWith('_') && part.endsWith('_') ? <em key={index}>{part.slice(1, -1)}</em> : part) }
  return <div className="automation-markdown">{markdown.split(/\n\s*\n/).filter(Boolean).map((block, index) => {
    if (block.startsWith('## ')) return <h4 key={index}>{inline(block.slice(3))}</h4>
    if (block.startsWith('# ')) return <h3 key={index}>{inline(block.slice(2))}</h3>
    if (block.split('\n').every((line) => line.startsWith('- '))) return <ul key={index}>{block.split('\n').map((line, i) => <li key={i}>{inline(line.slice(2))}</li>)}</ul>
    return <p key={index}>{inline(block)}</p>
  })}</div>
}

export function AutomationsScreen({ docs }: { docs: Document[] }) {
  const [rows, setRows] = useState<Automation[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [name, setName] = useState('')
  const [prompt, setPrompt] = useState('')
  const [chosen, setChosen] = useState('')
  const [interval, setInterval] = useState(1440)
  const [busy, setBusy] = useState('')
  const [selected, setSelected] = useState<Automation | null>(null)
  const [report, setReport] = useState('')
  const [reportError, setReportError] = useState('')
  const [reportRefresh, setReportRefresh] = useState(0)
  const [notice, setNotice] = useState('')
  const retry = useRef<() => void>(() => setRefresh((value) => value + 1))
  const operation = useRef<AbortController | null>(null)
  const reportRequest = useRef<AbortController | null>(null)
  const docId = chosen || drawingDocuments(docs)[0]?.doc_id || ''
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError('')
    retry.current = () => setRefresh((value) => value + 1)
    skillsApi.listAutomations(controller.signal).then((data) => { if (!controller.signal.aborted) setRows(data) })
      .catch((err: Error) => { if (!controller.signal.aborted) setError(err.message) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [refresh])
  useEffect(() => () => { operation.current?.abort(); reportRequest.current?.abort() }, [])
  useEffect(() => {
    reportRequest.current?.abort()
    const controller = new AbortController(); reportRequest.current = controller
    setReport(''); setReportError('')
    if (selected?.last_report) skillsApi.report(selected.id, controller.signal).then((text) => { if (!controller.signal.aborted) setReport(text) })
      .catch((err: Error) => { if (!controller.signal.aborted) setReportError(err.message) })
    return () => controller.abort()
  }, [selected, reportRefresh])
  async function act(key: string, fn: (signal: AbortSignal) => Promise<void>) {
    const controller = new AbortController(); operation.current = controller
    retry.current = () => { void act(key, fn) }
    setBusy(key); setError(''); setNotice('')
    try { await fn(controller.signal); if (!controller.signal.aborted) setNotice(key === 'create' ? 'Automation saved.' : key.startsWith('delete:') ? 'Automation deleted.' : key.startsWith('run:') ? 'Run complete.' : 'Report loaded.') }
    catch (err) { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : 'The automation could not be completed.') }
    finally { if (!controller.signal.aborted) setBusy('') }
  }
  return <section className="tools-screen" aria-label="Automations"><header className="tools-header"><div><h2><Clock3 size={19} />Automations</h2><p>Run a saved question on a schedule and keep its latest report.</p></div><Button variant="raised" disabled={!!busy || loading} onClick={() => { setSelected(null); setRefresh((value) => value + 1) }}>Refresh</Button></header>
    {error && <p role="alert" className="tools-message">{error} <Button disabled={!!busy || loading} onClick={() => retry.current()}>Retry</Button></p>}{notice && <p role="status" className="tools-message">{notice}</p>}{busy && <p role="status" className="tools-message">{busy === 'create' ? 'Saving automation…' : busy.startsWith('run:') ? 'Running the question and writing its report…' : busy.startsWith('delete:') ? 'Deleting automation…' : 'Loading report…'}</p>}
    <form className="tools-card tools-form" aria-label="Create automation" onSubmit={(event) => { event.preventDefault(); if (!busy && docId && name.trim() && prompt.trim()) void act('create', async (signal) => {
      const row = await skillsApi.createAutomation(name, prompt, docId, interval, signal)
      if (!signal.aborted) { setRows((data) => [...data, row]); setSelected(row); setName(''); setPrompt('') }
    }) }}><h3>Create an automation</h3><label>Automation name<input required maxLength={80} value={name} disabled={!!busy} onChange={(event) => setName(event.target.value)} placeholder="Window report" /></label><label>Automation prompt<textarea required maxLength={2000} value={prompt} disabled={!!busy} onChange={(event) => setPrompt(event.target.value)} placeholder="How many windows are there?" /></label>
      <div className="tools-controls"><DrawingPicker docs={docs} label="Automation drawing" value={docId} disabled={!!busy} onChange={setChosen} />
        <label>Schedule<select aria-label="Schedule" value={interval} disabled={!!busy} onChange={(event) => setInterval(Number(event.target.value))}>{schedules.map((schedule) => <option key={schedule.minutes} value={schedule.minutes}>{schedule.label}</option>)}</select></label></div>
      <p className="tools-muted">Repeats from creation or the last run. Next run times are shown in your local timezone.</p><Button type="submit" variant="raised" disabled={!!busy || loading || !docId || !name.trim() || !prompt.trim()}>Save automation</Button>
    </form>
    {loading ? <p role="status" className="tools-muted">Loading automations…</p> : !rows.length ? <p className="tools-muted">No automations saved yet.</p> : <div className="automation-list">{rows.map((row) => <article key={row.id} className="tools-card" aria-label={row.name} data-automation-id={row.id}><header><h3>{row.name}</h3><span className="tools-tag">{row.enabled ? scheduleLabel(row.interval_minutes) : 'Paused'}</span></header><p className="skill-prompt">{row.prompt}</p><p className="tools-muted">{row.doc_ids.map((id) => docs.find((doc) => doc.doc_id === id)?.title ?? id).join(', ')}</p><dl><div><dt>Last run</dt><dd>{runTime(row.last_run_at)}</dd></div><div><dt>Next run</dt><dd>{row.next_run_at ? runTime(row.next_run_at) : 'Paused'}</dd></div></dl>
      <div className="tools-row-actions"><Button variant="raised" disabled={!!busy} onClick={() => void act(`run:${row.id}`, async (signal) => { const updated = await skillsApi.runAutomation(row.id, signal); if (!signal.aborted) { setRows((data) => data.map((entry) => entry.id === row.id ? updated : entry)); setSelected(updated); if (!updated.last_report?.ok) throw new Error('The automation run failed. Read the report below and retry.'); } })}><Play size={14} />Run now</Button>
        <Button variant="ghost" disabled={!!busy || !row.last_report} onClick={() => void act(`report:${row.id}`, async (signal) => { const updated = await skillsApi.getAutomation(row.id, signal); if (!signal.aborted) setSelected(updated) })}>Last report</Button>
        <Button variant="ghost" aria-label={`Delete automation ${row.name}`} disabled={!!busy} onClick={() => void act(`delete:${row.id}`, async (signal) => { await skillsApi.deleteAutomation(row.id, signal); if (!signal.aborted) { setRows((data) => data.filter((entry) => entry.id !== row.id)); if (selected?.id === row.id) setSelected(null) } })}><Trash2 size={14} />Delete</Button></div>
    </article>)}</div>}
    {selected && <section className="tools-card automation-report" aria-label="Last automation report"><header><h3>Last report · {selected.name}</h3><Button variant="raised" disabled={!report} onClick={() => downloadReport(selected.name, report)}><Download size={14} />Export .md</Button></header>
      {!selected.last_report ? <p className="tools-muted">No report yet. Choose Run now to create one.</p> : reportError ? <p role="alert">{reportError} <Button onClick={() => setReportRefresh((value) => value + 1)}>Retry report</Button></p> : !report ? <p role="status" className="tools-muted">Loading last report…</p> : <><p className="tools-muted">{runTime(selected.last_run_at)} · {selected.last_report.ok ? 'Completed' : 'Run failed'}</p><ReportMarkdown markdown={report} /></>}
    </section>}
  </section>
}
