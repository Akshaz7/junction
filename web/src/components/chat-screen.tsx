import { useEffect, useRef, useState } from 'react'
import { ArrowRight, ArrowUp, AtSign, FileText, FolderOpen, Layers3, MapPin, MessageSquareText, Ruler, Search, Sparkles, X } from 'lucide-react'
import { Button } from './ui'
import { AnswerCard } from './answer-card'
import { workspaceApi } from '../lib/api'
import type { Answer, Citation, Document, TraceStep } from '../lib/types'

const starters = [
  { title: 'Count something on a plan', hint: 'Find windows, doors and more', question: 'How many windows are there?', icon: Search },
  { title: "Find a room’s area", hint: 'Check the space in your drawing', question: 'What is the area of this room?', icon: Ruler },
  { title: 'Where is it on level N?', hint: 'Locate it in the project', question: 'Where is the stair core on level 2?', icon: MapPin },
  { title: 'What does this drawing say about…', hint: 'Read the detail with its source', question: 'What does this drawing say about the doors?', icon: MessageSquareText },
]

type Mention = { start: number; end: number; query: string }

export function ChatScreen({ docs, loadingDocs, demo, contextDocument, hidden, onOpenCitation }: {
  docs: Document[]; loadingDocs: boolean; demo: boolean; contextDocument: Document | null; hidden: boolean
  onOpenCitation: (citation: Citation) => void
}) {
  const [draft, setDraft] = useState('')
  const [selected, setSelected] = useState<Document[]>(contextDocument ? [contextDocument] : [])
  const [answers, setAnswers] = useState<Answer[]>([])
  const [busy, setBusy] = useState(false)
  const [pendingQuestion, setPendingQuestion] = useState('')
  const [statuses, setStatuses] = useState<string[]>([])
  const [traces, setTraces] = useState<TraceStep[]>([])
  const [error, setError] = useState('')
  const [mention, setMention] = useState<Mention | null>(null)
  const [activeOption, setActiveOption] = useState(0)
  const chatId = useRef<string | null>(null)
  const submitting = useRef(false)
  const textarea = useRef<HTMLTextAreaElement>(null)
  const conversation = useRef<HTMLDivElement>(null)
  const picker = useRef<HTMLDivElement>(null)

  useEffect(() => { if (contextDocument) setSelected([contextDocument]) }, [contextDocument])
  useEffect(() => {
    if (conversation.current && (answers.length || busy)) conversation.current.scrollTop = conversation.current.scrollHeight
  }, [answers, statuses, traces, busy])
  useEffect(() => {
    if (!mention) return
    function close(event: PointerEvent) {
      if (!picker.current?.contains(event.target as Node) && event.target !== textarea.current) setMention(null)
    }
    document.addEventListener('pointerdown', close)
    return () => document.removeEventListener('pointerdown', close)
  }, [mention])

  const matches = mention ? docs.filter((doc) => !selected.some((item) => item.doc_id === doc.doc_id) &&
    `${doc.title} ${doc.doc_id} ${doc.source}`.toLowerCase().includes(mention.query.toLowerCase())) : []
  const optionIndex = Math.min(activeOption, Math.max(0, matches.length - 1))

  function updateMention(value: string, caret: number) {
    const match = value.slice(0, caret).match(/(?:^|\s)@([^@\n]*)$/)
    setMention(match ? { start: caret - match[1].length - 1, end: caret, query: match[1] } : null)
    setActiveOption(0)
  }

  function chooseDocument(doc: Document) {
    if (!mention) return
    setSelected((previous) => [...previous, doc])
    const value = draft.slice(0, mention.start) + draft.slice(mention.end)
    const caret = mention.start
    setDraft(value)
    setMention(null)
    textarea.current?.focus()
    requestAnimationFrame(() => textarea.current?.setSelectionRange(caret, caret))
  }

  async function ask(question: string) {
    if (!question.trim() || submitting.current || !docs.length) return
    submitting.current = true
    setBusy(true)
    setPendingQuestion(question.trim())
    setStatuses(['Thinking…'])
    setTraces([])
    setError('')
    setDraft('')
    setMention(null)
    const docIds = (selected.length ? selected : docs).map((doc) => doc.doc_id)
    const streamedTraces: TraceStep[] = []
    try {
      if (!chatId.current) chatId.current = await workspaceApi.createChat(docIds, question.trim().slice(0, 100))
      const answer = await workspaceApi.askQuestion(chatId.current, question.trim(), docIds, {
        onStatus: (text) => setStatuses((previous) => previous.at(-1) === text ? previous : [...previous, text]),
        onTrace: (trace) => { streamedTraces.push(trace); setTraces([...streamedTraces]) },
      })
      setAnswers((previous) => [...previous, { ...answer, trace: answer.trace.length ? answer.trace : streamedTraces }])
    } catch (err) {
      setDraft(question)
      setError(err instanceof Error ? err.message : 'The request failed. Please try again.')
    } finally {
      submitting.current = false
      setBusy(false)
      setPendingQuestion('')
    }
  }

  return <section className="chat-page" aria-label="Drawing questions" hidden={hidden}>
    <div ref={conversation} className={`conversation ${answers.length || busy ? 'has-answers' : ''}`}>
      {!answers.length && !busy && <div className="welcome">
        <div className="welcome-mark"><Layers3 size={30} strokeWidth={1.5} /></div>
        <p className="eyebrow">YOUR DRAWINGS, IN CONVERSATION</p>
        <h2>Where shall we start?</h2>
        <p className="intro">Ask about your project. Find the answer,<br className="desktop-break" /> with the source to back it up.</p>
        <div className="starter-grid">{starters.map(({ title, hint, question, icon: Icon }) => <button key={title} className="starter-card" disabled={loadingDocs || !docs.length} onClick={() => void ask(question)}>
          <span className="starter-icon"><Icon size={18} /></span><span><strong>{title}</strong><span>{hint}</span></span><ArrowRight size={15} />
        </button>)}</div>
        {demo && <p className="demo-note">Offline sample content generated for demo</p>}
      </div>}
      {answers.map((answer, index) => <AnswerCard key={`${answer.answer_id}-${index}`} answer={answer} docs={docs} demo={demo} onOpenCitation={onOpenCitation} />)}
      {busy && <div className="exchange pending-exchange" aria-busy="true">
        <div className="question-bubble">{pendingQuestion}</div>
        <div className="status-lines" role="status" aria-live="polite">{statuses.map((status, index) => <p key={index}><Sparkles size={15} />{status}</p>)}</div>
        {!!traces.length && <details className="answer-detail"><summary>Show thought process</summary>{traces.map((trace, index) => <p key={index}>{trace.detail}</p>)}</details>}
      </div>}
    </div>
    <div className="composer-area">
      {error && <p className="error-message" role="alert">{error}</p>}
      <form className="composer" onSubmit={(event) => { event.preventDefault(); if (!mention) void ask(draft) }}>
        {!!selected.length && <div className="selected-documents" aria-label="Selected documents">{selected.map((doc) => <span className="chip document-chip" key={doc.doc_id}><FileText size={13} /><span>{doc.title}</span><button type="button" disabled={busy} aria-label={`Remove ${doc.title}`} onClick={() => setSelected((previous) => previous.filter((item) => item.doc_id !== doc.doc_id))}><X size={13} /></button></span>)}</div>}
        <label className="sr-only" htmlFor="question">Ask about your drawings</label>
        <textarea ref={textarea} id="question" rows={2} placeholder="Ask anything. Type @ to include a document" value={draft} disabled={busy}
          role="combobox" aria-autocomplete="list" aria-expanded={!!mention} aria-controls={mention ? 'document-picker' : undefined} aria-activedescendant={mention && matches.length ? `document-option-${optionIndex}` : undefined}
          onChange={(event) => { setDraft(event.target.value); updateMention(event.target.value, event.target.selectionStart) }}
          onClick={(event) => updateMention(event.currentTarget.value, event.currentTarget.selectionStart)}
          onKeyDown={(event) => {
            if (event.nativeEvent.isComposing) return
            if (mention) {
              if (event.key === 'Escape') { event.preventDefault(); setMention(null); return }
              if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                event.preventDefault()
                setActiveOption((optionIndex + (event.key === 'ArrowDown' ? 1 : -1) + Math.max(1, matches.length)) % Math.max(1, matches.length))
                return
              }
              if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); if (matches[optionIndex]) chooseDocument(matches[optionIndex]); return }
            }
            if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void ask(draft) }
          }} />
        {mention && <div className="document-picker" ref={picker}>
          <p className="picker-heading">Include a document</p>
          <div id="document-picker" role="listbox" aria-label="Documents">{matches.map((doc, index) => <button type="button" role="option" aria-selected={index === optionIndex} id={`document-option-${index}`} key={doc.doc_id} onClick={() => chooseDocument(doc)}>
            <FileText size={16} /><span>{doc.title}<small>{doc.source}</small></span>
          </button>)}</div>
          {!matches.length && <p className="picker-empty">{loadingDocs ? 'Loading documents…' : 'No matching documents.'}</p>}
        </div>}
        <div className="composer-actions"><button className="document-context" type="button" disabled={busy || loadingDocs || !docs.length} onClick={() => {
          const next = draft + (draft && !/\s$/.test(draft) ? ' @' : '@')
          setDraft(next); updateMention(next, next.length); textarea.current?.focus()
        }}><FolderOpen size={15} />{loadingDocs ? 'Loading documents…' : selected.length ? `${selected.length} selected` : `All documents (${docs.length})`}<AtSign size={13} /></button>
          <Button type="submit" variant="primary" className="send-button" aria-label="Send question" disabled={!draft.trim() || busy || !docs.length || !!mention}><ArrowUp size={18} /></Button>
        </div>
      </form>
      <p className="composer-disclaimer">AI can make mistakes. Verify important information.</p>
    </div>
  </section>
}
