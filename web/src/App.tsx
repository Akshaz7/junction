import { useEffect, useState, type FormEvent } from 'react'
import { ArrowRight, ArrowUp, ChevronDown, FileText, FolderOpen, Layers3, MessageSquare, Plus, Search, Sparkles } from 'lucide-react'
import { Button } from './components/ui/button'
import { askQuestion, getDocuments, useMock } from './lib/api'
import type { Answer, Document } from './lib/types'

const starter = 'How many windows are in the sample plan?'

function AnswerText({ text }: { text: string }) {
  return text.split(/(\*\*.*?\*\*)/g).map((part, index) => part.startsWith('**')
    ? <strong key={index}>{part.slice(2, -2)}</strong> : part)
}

export default function App() {
  const [view, setView] = useState<'chat' | 'data'>('chat')
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
    <aside className="rail" aria-label="Workspace navigation">
      <a href="#" className="brand-mark" aria-label="Hologram home" onClick={() => setView('chat')}><Layers3 size={25} /></a>
      <div className="project-mark" title="Demo workspace">H</div>
      <nav>
        <button className={`rail-item ${view === 'chat' ? 'active' : ''}`} onClick={() => setView('chat')} aria-label="Chat" aria-current={view === 'chat' ? 'page' : undefined}><MessageSquare size={20} /><span>Chat</span></button>
        <button className={`rail-item ${view === 'data' ? 'active' : ''}`} onClick={() => setView('data')} aria-label="Data" aria-current={view === 'data' ? 'page' : undefined}><FolderOpen size={20} /><span>Data</span></button>
      </nav>
      <div className="workspace-avatar" title="Shared workspace">H</div>
    </aside>

    <main className="workspace">
      <header className="topbar">
        <div className="project-title"><span className="wordmark">Hologram</span><span className="topbar-divider" /><span className="workspace-name">Demo workspace</span></div>
        <span className="mode-label">{useMock ? 'Local demo' : 'Connected workspace'}</span>
      </header>
      <div className="pagebar">
        <h1>{view === 'chat' ? 'Chat' : 'Data'}</h1>
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
      </section> : <section className="data-page" aria-label="Project documents">
        <div className="data-header"><div><h2>Project documents</h2><p>The sources behind your answers.</p></div><label className="search-field"><Search size={16} /><input type="search" aria-label="Search documents" placeholder="Search documents" value={search} onChange={(event) => setSearch(event.target.value)} /></label></div>
        {error && <p className="error-message" role="alert">{error}</p>}
        {loadingDocs ? <p role="status">Loading documents…</p> : <div className="document-list">{docs.filter((doc) => doc.title.toLowerCase().includes(search.toLowerCase())).map((doc) => <article className="document-row" key={doc.doc_id}><span className="file-icon"><FileText size={22} /></span><div><h3>{doc.title}</h3><p>{doc.source} · {doc.formats.join(', ').toUpperCase()} · {doc.pages} {doc.pages === 1 ? 'page' : 'pages'}</p><small>{doc.credit} · {doc.licence}</small></div><Button variant="raised" onClick={() => setView('chat')}>Ask about it<ArrowRight size={15} /></Button></article>)}</div>}
        {!loadingDocs && !docs.filter((doc) => doc.title.toLowerCase().includes(search.toLowerCase())).length && <p className="empty-state">No documents found.</p>}
      </section>}
    </main>
  </div>
}
