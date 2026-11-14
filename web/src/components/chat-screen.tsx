import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { ArrowUp, AtSign, CalendarClock, FileSearch, FileText, FolderOpen, HardHat, Mic, Plus, Scale, X } from 'lucide-react'
import { Button } from './ui'
import { AnswerCard } from './answer-card'
import { DocumentViewer, useViewerSheet } from './document-viewer'
import { workspaceApi } from '../lib/api'
import type { Answer, Citation, Document, TraceStep } from '../lib/types'
import { ThinkingText } from './thinking-text'

const starters = [
  { title: 'Count on a plan', label: 'Count something on a plan', question: 'How many windows are there?', icon: Scale },
  { title: 'Find a room’s area', label: 'Find a room’s area', question: 'What is the area of this room?', icon: CalendarClock },
  { title: 'Locate something', label: 'Where is it on level N?', question: 'Where is the stair core on level 2?', icon: HardHat },
  { title: 'Read a drawing', label: 'What does this drawing say about…', question: 'What does this drawing say about the doors?', icon: FileSearch },
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
  const [viewer, setViewer] = useState<{ answer: Answer; citation: Citation; request: number } | null>(null)
  const [split, setSplit] = useState(48)
  const splitContainer = useRef<HTMLDivElement>(null)
  const sheet = useViewerSheet()
  const chatId = useRef<string | null>(null)
  const submitting = useRef(false)
  const textarea = useRef<HTMLTextAreaElement>(null)
  const conversation = useRef<HTMLDivElement>(null)
  const picker = useRef<HTMLDivElement>(null)

  useEffect(() => { if (contextDocument) setSelected([contextDocument]) }, [contextDocument])
  useEffect(() => {
    const node = conversation.current
    if (!node || (!answers.length && !busy)) return
    // Keep the current question visible as its answer grows. Long answers scroll
    // within the conversation; a follow-up starts at its own question.
    const latest = node.querySelector<HTMLElement>('.exchange:last-child')
    if (latest) node.scrollTop = Math.max(0, latest.offsetTop - 64)
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

  return <div ref={splitContainer} className={`chat-workspace ${viewer ? 'has-viewer' : ''}`} hidden={hidden} style={{ '--chat-split': `${split}%` } as CSSProperties}>
    <section className="chat-page" aria-label="Drawing questions" inert={!!viewer && sheet}>
    <div ref={conversation} className={`conversation ${answers.length || busy ? 'has-answers' : ''}`}>
      {!answers.length && !busy && <div className="welcome">
        <h2>Where shall we start?</h2>
        <div className="starter-grid">{starters.map(({ title, label, question, icon: Icon }) => <button key={title} aria-label={label} className="starter-card" disabled={loadingDocs || !docs.length} onClick={() => void ask(question)}>
          <Icon size={20} /><strong>{title}</strong>
        </button>)}</div>
        {demo && <p className="demo-note">Offline sample content generated for demo</p>}
      </div>}
      {answers.map((answer, index) => <AnswerCard key={`${answer.answer_id}-${index}`} answer={answer} docs={docs} demo={demo} activeCitation={viewer?.answer === answer ? viewer.citation : undefined} onOpenCitation={(citation) => {
        setViewer((previous) => ({ answer, citation, request: (previous?.request ?? 0) + 1 }))
        onOpenCitation(citation)
      }} />)}
      {busy && <div className="exchange pending-exchange" aria-busy="true">
        <div className="question-bubble">{pendingQuestion}</div>
        <div className="status-lines" role="status" aria-live="polite"><span className="thinking-mark" aria-hidden="true">H</span><ThinkingText text={statuses.at(-1) || 'Thinking…'} /></div>
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
        <div className="composer-actions"><button className="document-context" aria-label={selected.length ? `Document context: ${selected.length} selected` : `Include a document (${docs.length} available)`} title={selected.length ? `${selected.length} selected` : `All documents (${docs.length})`} type="button" disabled={busy || loadingDocs || !docs.length} onClick={() => {
          const next = draft + (draft && !/\s$/.test(draft) ? ' @' : '@')
          setDraft(next); updateMention(next, next.length); textarea.current?.focus()
        }}><Plus size={16} /><span className="sr-only"><FolderOpen size={15} />{loadingDocs ? 'Loading documents…' : selected.length ? `${selected.length} selected` : `All documents (${docs.length})`}<AtSign size={13} /></span></button><Mic className="composer-mic" size={16} aria-label="Voice input unavailable" />
          <Button type="submit" variant="primary" className="send-button" aria-label="Send question" disabled={!draft.trim() || busy || !docs.length || !!mention}><ArrowUp size={18} /></Button>
        </div>
      </form>
      <p className="composer-disclaimer">AI can make mistakes. Verify important information.</p>
    </div>
    </section>
    {viewer && <>
      <div className="viewer-split-handle" role="separator" aria-label="Resize chat and drawing" aria-orientation="vertical" aria-valuemin={35} aria-valuemax={65} aria-valuenow={Math.round(split)} tabIndex={0}
        onKeyDown={(event) => {
          if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); setSplit((previous) => Math.max(35, Math.min(65, previous + (event.key === 'ArrowLeft' ? -2 : 2)))) }
        }}
        onPointerDown={(event) => event.currentTarget.setPointerCapture(event.pointerId)}
        onPointerMove={(event) => {
          if (!event.currentTarget.hasPointerCapture(event.pointerId)) return
          const bounds = splitContainer.current!.getBoundingClientRect()
          setSplit(Math.max(35, Math.min(65, (event.clientX - bounds.left) / bounds.width * 100)))
        }}
        onPointerUp={(event) => event.currentTarget.releasePointerCapture(event.pointerId)} />
      <DocumentViewer key={viewer.request} answer={viewer.answer} citation={viewer.citation} sheet={sheet} onClose={() => setViewer(null)} />
    </>}
  </div>
}
