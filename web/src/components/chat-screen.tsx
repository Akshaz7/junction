import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { ArrowUp, AtSign, CalendarClock, FileSearch, FileText, FolderOpen, HardHat, Plus, Scale, X } from 'lucide-react'
import { Button } from './ui'
import { AnswerCard } from './answer-card'
import { DocumentViewer, useViewerSheet } from './document-viewer'
import { workspaceApi } from '../lib/api'
import type { Answer, Citation, Document, TraceStep } from '../lib/types'
import { ThinkingText } from './thinking-text'
import { MicButton } from './voice-controls'
import { chatLink, savedExchanges, type ChatExchange } from '../lib/chat-history'
import { chatLive } from '../lib/chat-live'
import { useSceneEdits } from '../lib/use-scene-edits'
import { DrawingEditsContext } from '../lib/scene-edit-context'
import { SkillPicker } from './skills-screen'

const starters = [
  { title: 'Count on a plan', label: 'Count something on a plan', question: 'How many windows are there?', icon: Scale },
  { title: 'Find a room’s area', label: 'Find a room’s area', question: 'What is the area of this room?', icon: CalendarClock },
  { title: 'Locate something', label: 'Where is it on level N?', question: 'Where is the stair core on level 2?', icon: HardHat },
  { title: 'Read a drawing', label: 'What does this drawing say about…', question: 'What does this drawing say about the doors?', icon: FileSearch },
]

type Mention = { start: number; end: number; query: string }

export function ChatScreen({ docs, loadingDocs, demo, contextDocument, hidden, onOpenCitation, onChatChange }: {
  docs: Document[]; loadingDocs: boolean; demo: boolean; contextDocument: Document | null; hidden: boolean
  onChatChange: (id: string | null) => void
  onOpenCitation: (citation: Citation) => void
}) {
  const [draft, setDraft] = useState('')
  const [selected, setSelected] = useState<Document[]>(contextDocument ? [contextDocument] : [])
  const [answers, setAnswers] = useState<ChatExchange[]>([])
  const [restoring, setRestoring] = useState(false)
  const [restoredDocIds, setRestoredDocIds] = useState<string[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [pendingQuestion, setPendingQuestion] = useState('')
  const [statuses, setStatuses] = useState<string[]>([])
  const [traces, setTraces] = useState<TraceStep[]>([])
  const [error, setError] = useState('')
  const [mention, setMention] = useState<Mention | null>(null)
  const [toolsOpen, setToolsOpen] = useState(false)
  const [activeOption, setActiveOption] = useState(0)
  const [viewer, setViewer] = useState<{ answer: Answer; citation: Citation; request: number } | null>(null)
  const [split, setSplit] = useState(48)
  const splitContainer = useRef<HTMLDivElement>(null)
  const sheet = useViewerSheet()
  const chatId = useRef<string | null>(null)
  const [liveChatId, setLiveChatId] = useState<string | null>(null)
  useEffect(() => { onChatChange(liveChatId) }, [liveChatId, onChatChange])
  const submitting = useRef(false)
  const textarea = useRef<HTMLTextAreaElement>(null)
  const conversation = useRef<HTMLDivElement>(null)
  const picker = useRef<HTMLDivElement>(null)
  const tools = useRef<HTMLDivElement>(null)
  const toolsButton = useRef<HTMLButtonElement>(null)
  const generation = useRef(0)
  const sceneEdits = useSceneEdits(liveChatId, answers, demo)
  const viewerDoc = viewer?.citation.doc_id
  const viewerCommands = answers.flatMap((exchange) => {
    const answer = exchange.answer
    return answer && !answer.answer.abstained && (answer.evidence.scene.doc_id || answer.doc_ids[0]) === viewerDoc
      ? answer.evidence.scene.commands ?? [] : []
  })

  useEffect(() => {
    let controller: AbortController | undefined
    function followLink() {
      controller?.abort()
      const link = chatLink(window.location.hash)
      if (!link) { setRestoring(false); return }
      const version = ++generation.current
      submitting.current = false
      chatId.current = null
      setLiveChatId(null)
      setBusy(false); setAnswers([]); setViewer(null); setError('')
      setMention(null); setToolsOpen(false); setPendingQuestion(''); setStatuses([]); setTraces([])
      setSelected([]); setRestoredDocIds(null); setDraft('')
      if (link.kind === 'question') {
        setRestoring(false)
        setDraft(link.question)
        return
      }
      setRestoring(true)
      controller = new AbortController()
      const signal = controller.signal
      workspaceApi.getChat(link.id, signal).then((chat) => {
        if (signal.aborted || generation.current !== version) return
        chatId.current = chat.id
        setLiveChatId(chat.id)
        setAnswers(savedExchanges(chat))
        const ids = [...new Set(chat.messages.flatMap((message) => message.answer?.doc_ids ?? []))]
        setRestoredDocIds(ids.length ? ids : chat.doc_id ? [chat.doc_id] : [])
      }).catch((err: unknown) => {
        if (!signal.aborted && generation.current === version) setError(err instanceof Error ? err.message : 'This chat could not be loaded.')
      }).finally(() => {
        if (!signal.aborted && generation.current === version) setRestoring(false)
      })
    }
    followLink()
    window.addEventListener('hashchange', followLink)
    return () => { controller?.abort(); generation.current++; window.removeEventListener('hashchange', followLink) }
  }, [])

  useEffect(() => {
    if (demo || !liveChatId) return
    let controller: AbortController | undefined
    const version = generation.current
    let pendingMessageId: string | null = null
    function refresh() {
      // The sender owns its SSE stream; socket echoes must not duplicate its exchange.
      if (submitting.current) return
      controller?.abort()
      controller = new AbortController()
      const signal = controller.signal
      workspaceApi.getChat(liveChatId!, signal).then((chat) => {
        if (signal.aborted || generation.current !== version || submitting.current) return
        const exchanges = savedExchanges(chat)
        const last = exchanges.at(-1)
        // A stored unanswered question is history. Only a user notification
        // observed on this connection establishes an active remote request.
        const pending = last?.id === pendingMessageId && !last.answer && !last.content ? exchanges.pop() : null
        setAnswers(exchanges)
        setPendingQuestion(pending?.question ?? '')
        setBusy(!!pending)
        if (!pending) { setStatuses([]); setTraces([]) }
        setError('')
      }).catch((err: unknown) => {
        if (!signal.aborted && generation.current === version && !submitting.current)
          setError(err instanceof Error ? err.message : 'This chat could not be refreshed.')
      })
    }
    const unsubscribe = chatLive.subscribe((event) => {
      if (event.type === 'connected' || event.type === 'disconnected') {
        // A remote request observed before suspension may never produce another
        // notification here. A reconnect snapshot is history, not an active job.
        pendingMessageId = null
        if (!submitting.current) {
          setBusy(false); setPendingQuestion(''); setStatuses([]); setTraces([])
        }
        if (event.type === 'connected') refresh()
        return
      }
      if (event.chat_id !== liveChatId || submitting.current) return
      if (event.type === 'chat.message') {
        pendingMessageId = event.role === 'user' ? event.message_id : null
        refresh()
      }
      else setStatuses((previous) => previous.at(-1) === event.text ? previous : [...previous, event.text])
    })
    return () => { controller?.abort(); unsubscribe() }
  }, [demo, liveChatId])

  useEffect(() => {
    let frame = 0
    function resume() {
      if (hidden || document.visibilityState === 'hidden' || (viewer && sheet)) return
      cancelAnimationFrame(frame)
      // WKWebView can retain the keyboard's scroll offset across native AR.
      // Keep the mounted input and its draft, and reveal it after layout resumes.
      frame = requestAnimationFrame(() => textarea.current?.scrollIntoView({ block: 'nearest', inline: 'nearest' }))
    }
    document.addEventListener('visibilitychange', resume)
    window.addEventListener('pageshow', resume)
    return () => {
      cancelAnimationFrame(frame)
      document.removeEventListener('visibilitychange', resume)
      window.removeEventListener('pageshow', resume)
    }
  }, [hidden, viewer, sheet])

  useEffect(() => {
    if (restoredDocIds) setSelected(docs.filter((doc) => restoredDocIds.includes(doc.doc_id)))
  }, [docs, restoredDocIds])

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
  useEffect(() => {
    if (busy || restoring || hidden) setToolsOpen(false)
  }, [busy, restoring, hidden])
  useEffect(() => {
    if (!toolsOpen) return
    tools.current?.querySelector<HTMLButtonElement>('button:not(:disabled)')?.focus()
    function close(event: PointerEvent) {
      if (!tools.current?.contains(event.target as Node) && !toolsButton.current?.contains(event.target as Node)) setToolsOpen(false)
    }
    function escape(event: KeyboardEvent) {
      if (event.key === 'Escape') { event.preventDefault(); setToolsOpen(false); toolsButton.current?.focus() }
    }
    document.addEventListener('pointerdown', close)
    document.addEventListener('keydown', escape)
    return () => { document.removeEventListener('pointerdown', close); document.removeEventListener('keydown', escape) }
  }, [toolsOpen])

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

  async function ask(question: string, documentIds?: string[]) {
    if (!question.trim() || submitting.current || restoring || !docs.length) return
    const version = generation.current
    submitting.current = true
    setBusy(true)
    setPendingQuestion(question.trim())
    setStatuses(['Thinking…'])
    setTraces([])
    setError('')
    setDraft('')
    setMention(null)
    const docIds = documentIds ?? (selected.length ? selected : docs).map((doc) => doc.doc_id)
    const streamedTraces: TraceStep[] = []
    try {
      if (!chatId.current) {
        const id = await workspaceApi.createChat(docIds, question.trim().slice(0, 100))
        if (generation.current !== version) return
        chatId.current = id
        setLiveChatId(id)
        // Preserve the active stream: a hashchange would reload this new chat.
        window.history.replaceState(window.history.state, '', `#/chat?chat=${encodeURIComponent(id)}`)
      }
      const answer = await workspaceApi.askQuestion(chatId.current, question.trim(), docIds, {
        onStatus: (text) => { if (generation.current === version) setStatuses((previous) => previous.at(-1) === text ? previous : [...previous, text]) },
        onTrace: (trace) => { if (generation.current === version) { streamedTraces.push(trace); setTraces([...streamedTraces]) } },
      })
      if (generation.current !== version) return
      setAnswers((previous) => [...previous, { id: answer.answer_id, question: answer.question, content: '', answer: { ...answer, trace: answer.trace.length ? answer.trace : streamedTraces } }])
    } catch (err) {
      if (generation.current !== version) return
      setDraft(question)
      setError(err instanceof Error ? err.message : 'The request failed. Please try again.')
    } finally {
      if (generation.current === version) {
        submitting.current = false
        setBusy(false)
        setPendingQuestion('')
      }
    }
  }

  async function openCommandItem(answer: Answer, itemId: string) {
    const docId = answer.evidence.scene.doc_id || answer.doc_ids[0]
    const version = generation.current
    try {
      const metadata = docs.find((doc) => doc.doc_id === docId) ?? await workspaceApi.getDocument(docId)
      const pages = await Promise.allSettled(Array.from({ length: metadata.pages }, (_, page) => workspaceApi.getPlanMap(docId, page + 1)))
      if (generation.current !== version) return
      const plan = pages.flatMap((page) => page.status === 'fulfilled' ? [page.value] : []).find((page) => page.items.some((item) => item.item_id === itemId && item.bbox_px))
      if (!plan) throw new Error('This item has no position on the available drawings.')
      const tags = { ...sceneEdits[docId]?.tags }
      for (const command of answer.evidence.scene.commands ?? []) Object.assign(tags, command.labels)
      const ids = new Set([itemId, ...Object.keys(tags), ...(answer.evidence.scene.commands ?? []).flatMap((command) => [...command.item_ids])])
      const boxes = plan.items.filter((item) => ids.has(item.item_id) && item.bbox_px).map((item, n) => ({
        item_id: item.item_id, page: plan.page, bbox_px: item.bbox_px!, label: tags[item.item_id] ?? item.tag ?? String(n + 1),
      }))
      const box = boxes.find((item) => item.item_id === itemId)!
      const citation: Citation = { n: 1, doc_id: docId, page: plan.page, kind: 'element', bbox_px: box.bbox_px, item_ids: [itemId], quote: null }
      const drawingAnswer = { ...answer, citations: [citation], evidence: { ...answer.evidence, boxes } }
      setViewer((previous) => ({ answer: drawingAnswer, citation, request: (previous?.request ?? 0) + 1 }))
      setError('')
      onOpenCitation(citation)
    } catch (err) {
      if (generation.current === version) setError(err instanceof Error ? err.message : 'The drawing could not be opened.')
    }
  }

  return <div ref={splitContainer} className={`chat-workspace ${viewer ? 'has-viewer' : ''}`} hidden={hidden} style={{ '--chat-split': `${split}%` } as CSSProperties}>
    <section className="chat-page" aria-label="Drawing questions" inert={!!viewer && sheet}>
    <div ref={conversation} className={`conversation ${answers.length || busy ? 'has-answers' : ''}`}>
      {restoring && <p className="chat-loading" role="status">Loading chat…</p>}
      {!answers.length && !busy && !restoring && <div className="welcome">
        <h2>Where shall we start?</h2>
        <div className="starter-grid">{starters.map(({ title, label, question, icon: Icon }) => <button key={title} aria-label={label} className="starter-card" disabled={loadingDocs || !docs.length} onClick={() => void ask(question)}>
          <Icon size={20} /><strong>{title}</strong>
        </button>)}</div>
        {demo && <p className="demo-note">Offline sample content generated for demo</p>}
      </div>}
      {/* SSE and saved snapshots use different message IDs for the same answer.
          Keep its controls mounted when a live refresh replaces the exchange. */}
      {answers.map((exchange, index) => exchange.answer ? <AnswerCard key={`${exchange.answer.answer_id}-${index}`} answer={exchange.answer} docs={docs} demo={demo} chatId={liveChatId} activeCitation={viewer?.answer.answer_id === exchange.answer.answer_id ? viewer.citation : undefined}
        edits={sceneEdits[exchange.answer.evidence.scene.doc_id || exchange.answer.doc_ids[0]]} busy={busy || restoring}
        onUndo={() => void ask('undo', [exchange.answer!.evidence.scene.doc_id || exchange.answer!.doc_ids[0]])} onOpenItem={(id) => void openCommandItem(exchange.answer!, id)} onOpenCitation={(citation) => {
        setViewer((previous) => ({ answer: exchange.answer!, citation, request: (previous?.request ?? 0) + 1 }))
        onOpenCitation(citation)
      }} /> : <article className="exchange" key={`${exchange.id}-${index}`}>
        {exchange.question && <div className="question-bubble">{exchange.question}</div>}
        <p className="answer-text">{exchange.content || 'No answer yet.'}</p>
      </article>)}
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
        <div className="composer-input"><label className="sr-only" htmlFor="question">Ask about your drawings</label>
        {!draft && <span className="phone-composer-placeholder" aria-hidden="true">Ask anything. Type @ to include a document</span>}
        <textarea ref={textarea} id="question" rows={2} placeholder="Ask anything. Type @ to include a document" value={draft} disabled={busy || restoring}
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
          }} /></div>
        {mention && <div className="document-picker" ref={picker}>
          <p className="picker-heading">Include a document</p>
          <div id="document-picker" role="listbox" aria-label="Documents">{matches.map((doc, index) => <button type="button" role="option" aria-selected={index === optionIndex} id={`document-option-${index}`} key={doc.doc_id} onClick={() => chooseDocument(doc)}>
            <FileText size={16} /><span>{doc.title}<small>{doc.source}</small></span>
          </button>)}</div>
          {!matches.length && <p className="picker-empty">{loadingDocs ? 'Loading documents…' : 'No matching documents.'}</p>}
        </div>}
        {toolsOpen && <div className="composer-tools" ref={tools} id="composer-tools" role="dialog" aria-label="Add to question">
          <button type="button" className="composer-document-option" disabled={loadingDocs || !docs.length} onClick={() => {
            const next = draft + (draft && !/\s$/.test(draft) ? ' @' : '@')
            setToolsOpen(false); setDraft(next); updateMention(next, next.length); textarea.current?.focus()
          }}><FolderOpen size={16} />Include a document<AtSign size={13} /></button>
          <p className="picker-heading">Skills</p>
          <SkillPicker disabled={busy || restoring || hidden} onPick={(prompt) => { setDraft(prompt); setMention(null); setToolsOpen(false); textarea.current?.focus() }} />
        </div>}
        <div className="composer-actions"><button ref={toolsButton} className="document-context" aria-label="Add to question" aria-haspopup="dialog" aria-expanded={toolsOpen} aria-controls={toolsOpen ? 'composer-tools' : undefined} title="Add documents or skills" type="button" disabled={busy || restoring || hidden} onClick={() => { setMention(null); setToolsOpen((open) => !open) }}><Plus size={16} /></button><MicButton disabled={busy || restoring || hidden} onText={(text) => { setDraft(text); setMention(null); textarea.current?.focus() }} />
          <Button type="submit" variant="primary" className="send-button" aria-label="Send question" disabled={!draft.trim() || busy || restoring || !docs.length || !!mention}><ArrowUp size={18} /></Button>
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
      <DrawingEditsContext value={sceneEdits}>
        <DocumentViewer key={viewer.request} answer={viewer.answer} citation={viewer.citation} sheet={sheet}
          chatId={liveChatId}
          edits={sceneEdits[viewer.citation.doc_id]} commands={viewerCommands.length ? viewerCommands : undefined} onClose={() => setViewer(null)} />
      </DrawingEditsContext>
    </>}
  </div>
}
