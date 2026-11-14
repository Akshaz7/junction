import { useEffect, useId, useRef, useState } from 'react'
import { Library, Play, Trash2 } from 'lucide-react'
import { skillsApi, type Skill } from '../lib/skills'
import type { Answer, Citation, Document } from '../lib/types'
import { AnswerCard } from './answer-card'
import { DocumentViewer, useViewerSheet } from './document-viewer'
import { Button } from './ui'
import './skills-screen.css'

/** Place inside the composer's actions; picking fills the draft without submitting it. */
export function SkillPicker({ onPick, disabled = false }: { onPick: (prompt: string) => void; disabled?: boolean }) {
  const [skills, setSkills] = useState<Skill[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [refresh, setRefresh] = useState(0)
  const id = useId()
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setError('')
    skillsApi.listSkills(controller.signal).then((rows) => { if (!controller.signal.aborted) setSkills(rows) })
      .catch((err: Error) => { if (!controller.signal.aborted) setError(err.message) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [refresh])
  return <span className="skill-picker"><label htmlFor={id} className="sr-only">Use a skill</label><Library size={14} aria-hidden="true" /><select id={id} aria-label="Use a skill" value="" disabled={disabled || loading || !!error || !skills.length} onChange={(event) => { const skill = skills.find((row) => row.id === event.target.value); if (skill) onPick(skill.prompt) }}>
    <option value="">{loading ? 'Loading skills…' : error ? 'Skills unavailable' : skills.length ? 'Skills' : 'No skills saved'}</option>{skills.map((skill) => <option key={skill.id} value={skill.id}>{skill.name}</option>)}
  </select>{error && <button type="button" disabled={disabled} title={error} onClick={() => setRefresh((value) => value + 1)}>Retry skills</button>}</span>
}

export function SkillsScreen({ docs }: { docs: Document[] }) {
  const [skills, setSkills] = useState<Skill[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [name, setName] = useState('')
  const [prompt, setPrompt] = useState('')
  const [chosen, setChosen] = useState('')
  const [busy, setBusy] = useState('')
  const [answer, setAnswer] = useState<Answer | null>(null)
  const [citation, setCitation] = useState<Citation | null>(null)
  const operation = useRef<AbortController | null>(null)
  const sheet = useViewerSheet()
  const docId = chosen || docs[0]?.doc_id || ''
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError('')
    skillsApi.listSkills(controller.signal).then((rows) => { if (!controller.signal.aborted) setSkills(rows) })
      .catch((err: Error) => { if (!controller.signal.aborted) setError(err.message) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [refresh])
  useEffect(() => () => operation.current?.abort(), [])
  async function act(key: string, fn: (signal: AbortSignal) => Promise<void>) {
    const controller = new AbortController(); operation.current = controller
    setBusy(key); setError('')
    try { await fn(controller.signal) }
    catch (err) { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : 'The skill could not be completed.') }
    finally { if (!controller.signal.aborted) setBusy('') }
  }
  return <div className={`skills-workspace ${answer && citation ? 'has-evidence' : ''}`}><section className="tools-screen" aria-label="Skills"><header className="tools-header"><div><h2><Library size={19} />Skills</h2><p>Save the questions you ask often and run them on a drawing.</p></div><Button variant="raised" disabled={!!busy || loading} onClick={() => setRefresh((value) => value + 1)}>Refresh</Button></header>
    {error && <p role="alert" className="tools-message">{error}</p>}{busy && <p role="status" className="tools-message">{busy === 'create' ? 'Saving skill…' : busy.startsWith('delete:') ? 'Deleting skill…' : 'Reading the drawing…'}</p>}
    <form className="tools-card tools-form" aria-label="Create skill" onSubmit={(event) => { event.preventDefault(); if (!busy && name.trim() && prompt.trim()) void act('create', async (signal) => { const skill = await skillsApi.createSkill(name, prompt, signal); if (!signal.aborted) { setSkills((rows) => [...rows, skill]); setName(''); setPrompt('') } }) }}>
      <h3>Create a skill</h3><label>Skill name<input required maxLength={80} value={name} disabled={!!busy} onChange={(event) => setName(event.target.value)} placeholder="Count windows" /></label><label>Skill prompt<textarea required maxLength={2000} value={prompt} disabled={!!busy} onChange={(event) => setPrompt(event.target.value)} placeholder="How many windows are there?" /></label>
      <Button type="submit" variant="raised" disabled={!!busy || loading || !name.trim() || !prompt.trim()}>Save skill</Button>
    </form>
    <div className="tools-controls"><label>Run on drawing<select aria-label="Run on drawing" value={docId} disabled={!!busy || !docs.length} onChange={(event) => { setChosen(event.target.value); setAnswer(null); setCitation(null) }}><option value="" disabled>Choose a drawing</option>{docs.map((doc) => <option key={doc.doc_id} value={doc.doc_id}>{doc.title}</option>)}</select></label></div>
    {!docs.length && <p className="tools-muted">Add a drawing in Data to run a skill.</p>}
    {loading ? <p role="status" className="tools-muted">Loading skills…</p> : !skills.length ? <p className="tools-muted">No skills available. Save your first question above.</p> : <div className="skills-grid">{skills.map((skill) => <article key={skill.id} className="tools-card skill-card" data-skill-id={skill.id} aria-label={skill.name}><header><h3>{skill.name}</h3><span className="tools-tag">{skill.builtin ? 'Starter' : 'Saved'}</span></header>{skill.description && <p className="tools-muted">{skill.description}</p>}<p className="skill-prompt">{skill.prompt}</p>
      <div className="tools-row-actions"><Button variant="raised" disabled={!!busy || !docId} onClick={() => void act(`run:${skill.id}`, async (signal) => { setAnswer(null); setCitation(null); const result = await skillsApi.runSkill(skill.id, docId, signal); if (!signal.aborted) setAnswer(result) })}><Play size={14} />Run skill</Button>
        {!skill.builtin && <Button variant="ghost" aria-label={`Delete skill ${skill.name}`} disabled={!!busy} onClick={() => void act(`delete:${skill.id}`, async (signal) => { await skillsApi.deleteSkill(skill.id, signal); if (!signal.aborted) setSkills((rows) => rows.filter((row) => row.id !== skill.id)) })}><Trash2 size={14} />Delete</Button>}
      </div></article>)}</div>}
    {answer && <section className="tools-card skill-answer" aria-label="Skill answer"><h3>Answer</h3><AnswerCard answer={answer} docs={docs} demo={false} onOpenCitation={setCitation} /></section>}
  </section>{answer && citation && <DocumentViewer key={`${answer.answer_id}-${citation.n}`} answer={answer} citation={citation} sheet={sheet} onClose={() => setCitation(null)} />}</div>
}
