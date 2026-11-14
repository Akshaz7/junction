import { useEffect, useState, type FormEvent } from 'react'
import { ArrowRight, ArrowUp, ChevronDown, FileText, FolderOpen, Layers3, Plus, Search, Sparkles } from 'lucide-react'
import { Badge, Button, Input } from './components/ui'
import { ProjectSwitcher, WorkspaceNavigation, navigation } from './components/workspace-navigation'
import { PlaceholderPage } from './components/placeholder-page'
import { askQuestion, getDocuments, useMock } from './lib/api'
import { navigate, useRoute } from './lib/router'
import type { Answer, Document } from './lib/types'

const starter = 'How many windows are in the sample plan?'

function AnswerText({ text }: { text: string }) {
  return text.split(/(\*\*.*?\*\*)/g).map((part, index) => part.startsWith('**')
    ? <strong key={index}>{part.slice(2, -2)}</strong> : part)
}

export default function App() {
  const view = useRoute()
  const [docs, setDocs] = useState<Document[]>([])
  const [loadingDocs, setLoadingDocs] = useState(true)
  const [draft, setDraft] = useState('')
  const [answers, setAnswers] = useState<Answer[]>([])
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')

  useEffect(() => {
    let active = true
    getDocuments().then((documents) => { if (active) setDocs(documents) })
      .catch((err: Error) => { if (active) setError(err.message) })
      .finally(() => { if (active) setLoadingDocs(false) })
    return () => { active = false }
  }, [])

  async function ask(question: string) {
    if (!question.trim() || busy || !docs.length) return
    setBusy(true)
    setStatus('Thinking…')
    setError('')
    setDraft('')
    try {
      const answer = await askQuestion(question.trim(), docs.map((doc) => doc.doc_id), setStatus)
      setAnswers((previous) => [...previous, answer])
    } catch (err) {
      setDraft(question)
      setError(err instanceof Error ? err.message : 'The request failed. Please try again.')
    } finally {
      setBusy(false)
      setStatus('')
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    void ask(draft)
  }

  return <div className="app-shell">
    <a href="#main-content" className="skip-link" onClick={(event) => { event.preventDefault(); document.getElementById('main-content')?.focus() }}>Skip to content</a>
    <WorkspaceNavigation route={view} />

    <main className="workspace" id="main-content" tabIndex={-1}>
      <header className="topbar">
        <div className="project-title"><span className="wordmark">Hologram</span><span className="topbar-divider" /><span className="workspace-name">Demo workspace</span><div className="mobile-project"><ProjectSwitcher /></div></div>
        <Badge variant={useMock ? 'neutral' : 'success'}>{useMock ? 'Local demo' : 'Connected workspace'}</Badge>
      </header>
      <div className="pagebar">
        <h1>{navigation.find((item) => item.route === view)!.label}</h1>
        {view === 'chat' && <Button variant="raised" disabled={busy} onClick={() => { setAnswers([]); setDraft(''); setError('') }}><Plus size={16} />New chat</Button>}
      </div>

      {view === 'chat' ? <section className="chat-page" aria-label="Drawing questions">
        <div className={`conversation ${answers.length ? 'has-answers' : ''}`} aria-live="polite">
          {!answers.length && <div className="welcome">
            <div className="welcome-mark"><Layers3 size={30} strokeWidth={1.5} /></div>
            <p className="eyebrow">YOUR DRAWINGS, IN CONVERSATION</p>
            <h2>Where shall we start?</h2>
            <p className="intro">Ask about your project. Find the answer,<br className="desktop-break" /> with the source to back it up.</p>
            <button className="starter-card" disabled={loadingDocs || busy || !docs.length} onClick={() => void ask(starter)}>
              <span className="starter-icon"><Search size={19} /></span>
              <span><strong>Start with the drawing</strong><span>How many windows are in the sample plan?</span></span>
              <ArrowRight size={17} />
            </button>
            {useMock && <p className="demo-note">Sample content generated for demo</p>}
          </div>}
          {answers.map((answer, index) => <article className="exchange" key={`${answer.answer_id}-${index}`}>
            <div className="question-bubble">{answer.question}</div>
            <div className="answer-brand"><Layers3 size={17} /><strong>Hologram</strong>{useMock && <span>Demo answer</span>}</div>
            <p className="answer-text"><AnswerText text={answer.answer.text_md} /></p>
            {!!answer.citations.length && <>
              <h3 className="source-heading">Where it is set out</h3>
              <ol className="source-list">{answer.citations.map((citation) => <li key={citation.n}><span className="citation">{citation.n}</span><FileText size={15} /><span>{docs.find((doc) => doc.doc_id === citation.doc_id)?.title ?? citation.doc_id}<small>Page {citation.page}</small></span></li>)}</ol>
              <details className="answer-detail"><summary>Sources ({answer.citations.length})</summary>{answer.citations.map((citation) => <p key={citation.n}>[{citation.n}] {citation.item_ids.join(', ')} · Page {citation.page}</p>)}</details>
            </>}
            <details className="answer-detail"><summary>Show thought process</summary>{answer.trace.map((trace, i) => <p key={i}>{trace.detail}</p>)}</details>
          </article>)}
          {busy && <p className="status" role="status"><Sparkles size={16} />{status}</p>}
        </div>
        <div className="composer-area">
          {error && <p className="error-message" role="alert">{error}</p>}
          <form className="composer" onSubmit={submit}>
            <label className="sr-only" htmlFor="question">Ask about your drawings</label>
            <textarea id="question" rows={2} placeholder="Ask about your drawings…" value={draft} disabled={busy} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void ask(draft) }
            }} />
            <div className="composer-actions"><span className="document-context"><FolderOpen size={15} />{loadingDocs ? 'Loading documents…' : `${docs.length} ${docs.length === 1 ? 'document' : 'documents'}`}<ChevronDown size={13} /></span><Button type="submit" variant="primary" className="send-button" aria-label="Send question" disabled={!draft.trim() || busy || !docs.length}><ArrowUp size={18} /></Button></div>
          </form>
          <p className="composer-disclaimer">AI can make mistakes. Verify important information.</p>
        </div>
      </section> : view === 'data' ? <section className="data-page" aria-label="Project documents">
        <div className="data-header"><div><h2>Project documents</h2><p>The sources behind your answers.</p></div><label className="search-field"><Search size={16} /><Input type="search" aria-label="Search documents" placeholder="Search documents" value={search} onChange={(event) => setSearch(event.target.value)} /></label></div>
        {error && <p className="error-message" role="alert">{error}</p>}
        {loadingDocs ? <p role="status">Loading documents…</p> : <div className="document-list">{docs.filter((doc) => doc.title.toLowerCase().includes(search.toLowerCase())).map((doc) => <article className="document-row" key={doc.doc_id}><span className="file-icon"><FileText size={22} /></span><div><h3>{doc.title}</h3><p>{doc.source} · {doc.formats.join(', ').toUpperCase()} · {doc.pages} {doc.pages === 1 ? 'page' : 'pages'}</p><small>{doc.credit} · {doc.licence}</small></div><Button variant="raised" onClick={() => navigate('chat')}>Ask about it<ArrowRight size={15} /></Button></article>)}</div>}
        {!loadingDocs && !docs.filter((doc) => doc.title.toLowerCase().includes(search.toLowerCase())).length && <p className="empty-state">No documents found.</p>}
      </section> : <PlaceholderPage route={view} />}
    </main>
  </div>
}
