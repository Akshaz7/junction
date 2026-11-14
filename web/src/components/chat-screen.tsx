import { askUntilReadable, STILL_READING_STATUS } from '../lib/still-reading'
import { sceneOpen, sceneOpenCitation } from '../lib/scene-open'
import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { ArrowUp, AtSign, CalendarClock, FileSearch, FileText, FolderOpen, HardHat, Paperclip, Plus, Scale, Upload, X } from 'lucide-react'
import { Button } from './ui'
import { AnswerCard } from './answer-card'
import { rememberChat } from '../lib/known-chats'
import { acceptPairProof, isPairedChat, registerChat } from '../lib/pairing'
import { NO_ANSWER_MESSAGE } from '../lib/answer-text'
import { DocumentViewer, useViewerSheet } from './document-viewer'
import { workspaceApi } from '../lib/api'
import type { Answer, Citation, Document, TraceStep } from '../lib/types'
import { ThinkingText } from './thinking-text'
import { MicButton } from './voice-controls'
import { chatLink, savedExchanges, type ChatExchange } from '../lib/chat-history'
import { chatLive } from '../lib/chat-live'
import { useSceneEdits } from '../lib/use-scene-edits'
import { DrawingEditsContext } from '../lib/scene-edit-context'
import { needsDocument } from '../lib/needs-document'
import { SkillPicker } from './skills-screen'
import { FollowBanner, useFollow } from './follow-banner'
import { getFollow } from '../lib/chat-follow'
import './follow-banner.css'
import { UploadDialog } from './upload-dialog'
import { isFileDrag, pickDroppedFile } from '../lib/file-drag'

const starters = [
  { title: 'Count on a plan', label: 'Count something on a plan', question: 'How many windows are there?', icon: Scale },
  { title: 'Find a room’s area', label: 'Find a room’s area', question: 'What is the area of this room?', icon: CalendarClock },
  { title: 'Locate something', label: 'Where is it on level N?', question: 'Where is the stair core on level 2?', icon: HardHat },
  { title: 'Read a drawing', label: 'What does this drawing say about…', question: 'What does this drawing say about the doors?', icon: FileSearch },
]

type Mention = { start: number; end: number; query: string }

export function ChatScreen({ docs, loadingDocs, demo, contextDocument, hidden, onOpenCitation, onChatChange, onRefresh, projectId = null }: {
  projectId?: string | null
  docs: Document[]; loadingDocs: boolean; demo: boolean; contextDocument: Document | null; hidden: boolean
  onChatChange: (id: string | null) => void
  onRefresh?: () => Promise<void>
  onOpenCitation: (citation: Citation) => void
}) {
  const [draft, setDraft] = useState('')
  const [selected, setSelected] = useState<Document[]>(contextDocument ? [contextDocument] : [])
  const [answers, setAnswers] = useState<ChatExchange[]>([])
  const [restoring, setRestoring] = useState(false)
  const [restoredDocIds, setRestoredDocIds] = useState<string[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [pendingQuestion, setPendingQuestion] = useState('')
  const catchUp = useRef(false) // opened mid-answer: refetch once the live subscription is up
  const expectingAnswer = useRef(false) // a live user message arrived and its answer has not
  const [statuses, setStatuses] = useState<string[]>([])
  const [traces, setTraces] = useState<TraceStep[]>([])
  const [streamText, setStreamText] = useState('')
  const [error, setError] = useState('')
  // A question whose stream ended without an answer: kept on screen with Retry.
  const [failed, setFailed] = useState<{ question: string; docIds: string[] } | null>(null)
  const [mention, setMention] = useState<Mention | null>(null)
  const [needDoc, setNeedDoc] = useState(false)
  const blocked = useRef('')
  const [toolsOpen, setToolsOpen] = useState(false)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [droppedFile, setDroppedFile] = useState<File | null>(null)
  const [fileOver, setFileOver] = useState(false)
  const dragDepth = useRef(0)
  const [activeOption, setActiveOption] = useState(0)
  const [viewer, setViewer] = useState<{ answer: Answer; citation: Citation; request: number; mode?: '2d' | '3d' } | null>(null)
  const [split, setSplit] = useState(48)
  const splitContainer = useRef<HTMLDivElement>(null)
  useEffect(() => {
    document.documentElement.style.setProperty('--chat-split-live', String(split / 100))
    return () => { document.documentElement.style.removeProperty('--chat-split-live') }
  }, [split])
  const sheet = useViewerSheet()
  const chatId = useRef<string | null>(null)
  const [liveChatId, setLiveChatId] = useState<string | null>(null)
  useEffect(() => { onChatChange(liveChatId) }, [liveChatId, onChatChange])
  // Created here, opened from History or a shared link: this browser may follow it from now on.
  useEffect(() => { if (liveChatId) rememberChat(liveChatId) }, [liveChatId])
  const submitting = useRef(false)
  const textarea = useRef<HTMLTextAreaElement>(null)
  const conversation = useRef<HTMLDivElement>(null)
  const picker = useRef<HTMLDivElement>(null)
  const tools = useRef<HTMLDivElement>(null)
  const toolsButton = useRef<HTMLButtonElement>(null)
  const generation = useRef(0)
  const sceneEdits = useSceneEdits(liveChatId, answers, demo)
  const viewerDoc = viewer?.citation.doc_id
  // FIX-2: a new answer about the document already open updates the open 2D/3D pane in place (no remount, no reload).
  const lastAnswerId = useRef<string | null>(null)
  useEffect(() => {
    const latest = [...answers].reverse().find((exchange) => exchange.answer)?.answer
    if (!latest || lastAnswerId.current === latest.answer_id) return
    const seen = lastAnswerId.current !== null
    lastAnswerId.current = latest.answer_id
    if (!seen || latest.answer.abstained) return
    const docId = latest.evidence.scene.doc_id || latest.doc_ids[0]
    if (sceneOpen(latest) === '3d') { // CONTRACT 3.3: same path as the Visualise it button
      const citation = sceneOpenCitation(latest)
      if (citation) { setViewer((previous) => ({ answer: latest, citation, request: (previous?.request ?? 0) + 1, mode: '3d' })); onOpenCitation(citation); return }
    }
    setViewer((previous) => {
      if (!previous || previous.citation.doc_id !== docId) return previous
      const citation = latest.citations.find((entry) => entry.doc_id === docId && entry.page === previous.citation.page) ?? latest.citations.find((entry) => entry.doc_id === docId)
      return citation ? { answer: latest, citation, request: previous.request + 1 } : previous
    })
  }, [answers])
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
      const drawing = window.location.hash.startsWith('#/chat?') ? new URLSearchParams(window.location.hash.split('?')[1]).get('doc') : null
      if (!link && !drawing) { setRestoring(false); return }
      const version = ++generation.current
      submitting.current = false
      chatId.current = null
      setLiveChatId(null)
      setBusy(false); setAnswers([]); setViewer(null); setError(''); setFailed(null); lastAnswerId.current = null
      setMention(null); setToolsOpen(false); setPendingQuestion(''); setStatuses([]); setTraces([])
      setSelected([]); setRestoredDocIds(null); setDraft('')
      if (drawing && !link) {
        setRestoring(false)
        setRestoredDocIds([drawing])
        return
      }
      if (!link) return
      if (link.kind === 'question') {
        setRestoring(false)
        setDraft(link.question)
        if (new URLSearchParams(window.location.hash.split('?')[1]).get('send') === '1') autoSend.current = link.question
        return
      }
      setRestoring(true)
      controller = new AbortController()
      const signal = controller.signal
      workspaceApi.getChat(link.id, signal).then((chat) => {
        if (signal.aborted || generation.current !== version) return
        chatId.current = chat.id
        setLiveChatId(chat.id)
        // A chat opened while its question is still being answered (auto-open on a paired phone): show the
        // in-progress state instead of a failed exchange, and keep following the live events.
        const opened = savedExchanges(chat)
        const lastOpened = opened.at(-1)
        const pendingOpened = chat.active && lastOpened && !lastOpened.answer && !lastOpened.content ? opened.pop() : null
        setAnswers(opened)
        if (pendingOpened && chat.active) {
          catchUp.current = true
          setPendingQuestion(pendingOpened.question); setBusy(true)
          setStatuses(chat.active.statuses.length ? chat.active.statuses : ['Thinking…'])
          setTraces(chat.active.traces ?? []); setStreamText(chat.active.text ?? '')
        }
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
        // The server reports a question that is still being answered (also to a device that joined
        // mid-answer): show its status lines and trace so far, then keep following live events.
        const active = chat.active
        const pending = (active || expectingAnswer.current) && last && !last.answer && !last.content ? exchanges.pop() : null
        setAnswers(exchanges)
        setPendingQuestion(pending ? pending.question : '')
        setBusy(!!pending)
        setStatuses(pending ? (active?.statuses.length ? active.statuses : ['Thinking…']) : [])
        setTraces(pending ? active?.traces ?? [] : [])
        setStreamText(pending ? active?.text ?? '' : '')
        setError('')
      }).catch((err: unknown) => {
        if (!signal.aborted && generation.current === version && !submitting.current)
          setError(err instanceof Error ? err.message : 'This chat could not be refreshed.')
      })
    }
    if (catchUp.current) { catchUp.current = false; refresh() } // events missed between the opening snapshot and this subscription
    const unsubscribe = chatLive.subscribe((event) => {
      // A (re)connect snapshot also recovers everything missed while backgrounded or in native AR.
      if (event.type === 'connected') { expectingAnswer.current = false; refresh(); return }
      if (event.type === 'disconnected') return
      if (event.chat_id !== liveChatId || submitting.current) return
      if (event.type === 'chat.message' && event.role === 'user') expectingAnswer.current = true
      else if (event.type === 'chat.message' || event.type === 'chat.done') expectingAnswer.current = false
      if (event.type === 'chat.message' && event.role === 'user' && event.text) {
        // Show the question straight from the event; the snapshot fetch below only reconciles.
        setPendingQuestion(event.text); setBusy(true); setStatuses(['Thinking…']); setTraces([]); setStreamText(''); setError(''); setFailed(null)
        refresh()
      } else if (event.type === 'chat.message' || event.type === 'chat.done') refresh()
      else if (event.type === 'chat.status') setStatuses((previous) => previous.at(-1) === event.text ? previous : [...previous, event.text])
      else if (event.type === 'chat.delta') setStreamText(event.text)
      else if (event.type === 'chat.trace') setTraces((previous) => JSON.stringify(previous.at(-1)) === JSON.stringify(event.step) ? previous : [...previous, event.step])
    })
    return () => { controller?.abort(); unsubscribe() }
  }, [demo, liveChatId])

  // Another device asked a question in a different chat: banner (or auto-open when "follow" is on).
  const [incoming, setIncoming] = useState<{ chatId: string; question: string } | null>(null)
  const [following] = useFollow()
  const followingRef = useRef(following)
  useEffect(() => { followingRef.current = following }, [following])
  useEffect(() => {
    if (demo) return
    return chatLive.subscribe((event) => {
      if (event.type === 'pair.chat') {
        // A paired device just started this chat: open it now, ahead of its first message event.
        void acceptPairProof(event.chat_id, event.proof).then((mine) => {
          if (mine && (followingRef.current || getFollow()) && !submitting.current && event.chat_id !== chatId.current)
            window.location.hash = `#/chat?chat=${encodeURIComponent(event.chat_id)}`
        })
        return
      }
      if (event.type !== 'chat.message' || event.role !== 'user' || submitting.current) return
      if (event.chat_id === chatId.current) return
      // Strangers' chats never raise the notice: only with Follow on, and only for chats this browser knows.
      if (!followingRef.current) return
      void isPairedChat(event.chat_id, { failOpen: true }).then((known) => {
        if (known && followingRef.current && !submitting.current) window.location.hash = `#/chat?chat=${encodeURIComponent(event.chat_id)}`
      })
    })
  }, [demo])
  useEffect(() => { if (liveChatId) setIncoming((previous) => previous?.chatId === liveChatId ? null : previous) }, [liveChatId])
  function openIncoming(id: string) {
    setIncoming(null)
    window.location.hash = `#/chat?chat=${encodeURIComponent(id)}`
  }

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
  }, [answers, statuses, traces, busy, streamText])
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

  function attachDocument(doc: Document) {
    setSelected((previous) => previous.some((item) => item.doc_id === doc.doc_id) ? previous : [...previous, doc])
    setNeedDoc(false)
  }

  function openUpload(file: File | null = null) {
    setDroppedFile(file); setToolsOpen(false); setMention(null); setUploadOpen(true)
  }

  const canDrop = !busy && !restoring && !hidden && !demo
  const dropHandlers = {
    onDragEnter: (event: React.DragEvent) => {
      if (!canDrop || !isFileDrag(event.dataTransfer)) return
      event.preventDefault(); dragDepth.current++; setFileOver(true)
    },
    onDragOver: (event: React.DragEvent) => {
      if (!canDrop || !isFileDrag(event.dataTransfer)) return
      event.preventDefault(); event.dataTransfer.dropEffect = 'copy'
    },
    onDragLeave: (event: React.DragEvent) => {
      if (!isFileDrag(event.dataTransfer)) return
      dragDepth.current = Math.max(0, dragDepth.current - 1)
      if (!dragDepth.current) setFileOver(false)
    },
    onDrop: (event: React.DragEvent) => {
      if (!isFileDrag(event.dataTransfer)) return
      event.preventDefault(); dragDepth.current = 0; setFileOver(false)
      if (!canDrop) return
      const picked = pickDroppedFile(event.dataTransfer.files)
      if (!picked) return
      if ('error' in picked) { setError(picked.error); return }
      setError(''); openUpload(picked.file)
    },
  }

  function chooseDocument(doc: Document) {
    if (!mention) return
    setSelected((previous) => [...previous, doc])
    setNeedDoc(false)
    if (blocked.current) { const held = blocked.current; blocked.current = ''; setMention(null); void ask(held, [doc.doc_id]); return }
    const value = draft.slice(0, mention.start) + draft.slice(mention.end)
    const caret = mention.start
    setDraft(value)
    setMention(null)
    textarea.current?.focus()
    requestAnimationFrame(() => textarea.current?.setSelectionRange(caret, caret))
  }

  /** Stoa starter cards fill the composer; the person edits and sends. */
  function fillComposer(text: string) {
    setDraft(text); setMention(null)
    requestAnimationFrame(() => {
      const box = textarea.current
      if (!box) return
      box.focus(); box.setSelectionRange(text.length, text.length)
    })
  }

  const composerArea = useRef<HTMLDivElement>(null)
  // Phone: the composer stays reachable under the viewer sheet; the sheet is sized to leave room for it.
  useEffect(() => {
    const node = composerArea.current, host = splitContainer.current
    if (!node || !host || typeof ResizeObserver === 'undefined') return
    const update = () => host.style.setProperty('--composer-h', `${node.offsetHeight}px`)
    update()
    const observer = new ResizeObserver(update)
    observer.observe(node)
    return () => observer.disconnect()
  }, [viewer, sheet])
  // A question sent from a project page arrives as #/chat?question=...&send=1 and is asked once the documents are known.
  const autoSend = useRef<string | null>(null)
  useEffect(() => {
    const text = autoSend.current
    if (text === null || restoring || !docs.length || draft !== text) return
    autoSend.current = null
    void ask(text)
  }) // eslint-disable-line react-hooks/exhaustive-deps
  async function ask(question: string, documentIds?: string[]) {
    if (!question.trim() || submitting.current || restoring || !docs.length) return
    // A drawing question with nothing attached would hang on "Thinking…": ask for a document and keep the text.
    if (!documentIds && !selected.length && !chatId.current && needsDocument(question)) { blocked.current = question; setNeedDoc(true); return }
    setNeedDoc(false)
    if (viewer && sheet) setViewer(null) // the answer streams into the conversation behind the sheet
    const version = generation.current
    submitting.current = true
    setBusy(true)
    setPendingQuestion(question.trim())
    setStatuses(['Thinking…'])
    setTraces([])
    setStreamText('')
    setError('')
    setFailed(null)
    setDraft('')
    setMention(null)
    const docIds = documentIds ?? (selected.length ? selected : docs).map((doc) => doc.doc_id)
    const streamedTraces: TraceStep[] = []
    try {
      if (!chatId.current) {
        const id = await workspaceApi.createChat(docIds, question.trim().slice(0, 100), projectId)
        if (generation.current !== version) return
        chatId.current = id
        await registerChat(id) // paired devices can now recognise this chat
        if (generation.current !== version) return
        setLiveChatId(id)
        // Preserve the active stream: a hashchange would reload this new chat.
        window.history.replaceState(window.history.state, '', `#/chat?chat=${encodeURIComponent(id)}${projectId ? `&project=${encodeURIComponent(projectId)}` : ''}`)
      }
      const answer = await askUntilReadable(() => workspaceApi.askQuestion(chatId.current!, question.trim(), docIds, {
        onStatus: (text) => { if (generation.current === version) setStatuses((previous) => previous.at(-1) === text ? previous : [...previous, text]) },
        onDelta: (text) => { if (generation.current === version) setStreamText(text) },
        onTrace: (trace) => { if (generation.current === version) { streamedTraces.push(trace); setTraces([...streamedTraces]) } },
      }), { cancelled: () => generation.current !== version, onWait: () => { setStreamText(''); setStatuses([STILL_READING_STATUS]) } })
      if (generation.current !== version) return
      setAnswers((previous) => [...previous, { id: answer.answer_id, question: answer.question, content: '', answer: { ...answer, trace: answer.trace.length ? answer.trace : streamedTraces } }])
    } catch (err) {
      if (generation.current !== version) return
      setDraft(question)
      setFailed({ question: question.trim(), docIds })
      setError(err instanceof Error ? err.message : 'The request failed. Please try again.')
    } finally {
      if (generation.current === version) {
        submitting.current = false
        setBusy(false)
        setPendingQuestion('')
        setStreamText('')
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
      setViewer((previous) => ({ answer: drawingAnswer, citation, request: (previous?.request ?? 0) + 1, mode: '2d' }))
      setError('')
      onOpenCitation(citation)
    } catch (err) {
      if (generation.current === version) setError(err instanceof Error ? err.message : 'The drawing could not be opened.')
    }
  }

  return <><FollowBanner incoming={incoming} onOpen={openIncoming} onDismiss={() => setIncoming(null)} />
  <div ref={splitContainer} className={`chat-workspace ${viewer ? 'has-viewer' : ''}`} hidden={hidden} style={{ '--chat-split': `${split}%` } as CSSProperties}>
    <section className="chat-page" aria-label="Drawing questions" data-file-over={fileOver || undefined} {...dropHandlers}>
    {fileOver && <div className="composer-drop-overlay" data-testid="composer-drop-overlay" aria-hidden="true"><Upload size={28} /><strong>Drop to upload and ask about it</strong><span>PDF, PNG, JPG, DXF or IFC</span></div>}
    <div ref={conversation} inert={!!viewer && sheet} className={`conversation ${answers.length || busy ? 'has-answers' : ''}`}>
      {restoring && <p className="chat-loading" role="status">Loading chat…</p>}
      {!answers.length && !busy && !restoring && !failed && <div className="welcome">
        <h2>Where shall we start?</h2>
        <div className="starter-grid">{starters.map(({ title, label, question, icon: Icon }) => <button key={title} aria-label={label} className="starter-card" disabled={loadingDocs || !docs.length} onClick={() => fillComposer(question)}>
          <Icon size={20} /><strong>{title}</strong>
        </button>)}</div>
        {demo && <p className="demo-note">Offline sample content generated for demo</p>}
      </div>}
      {/* SSE and saved snapshots use different message IDs for the same answer.
          Keep its controls mounted when a live refresh replaces the exchange. */}
      {answers.map((exchange, index) => exchange.answer ? <AnswerCard key={`${exchange.answer.answer_id}-${index}`} onAsk={(question) => void ask(question, selected.length ? undefined : exchange.answer?.doc_ids)} answer={exchange.answer} docs={docs} demo={demo} chatId={liveChatId} activeCitation={viewer?.answer.answer_id === exchange.answer.answer_id ? viewer.citation : undefined}
        edits={sceneEdits[exchange.answer.evidence.scene.doc_id || exchange.answer.doc_ids[0]]} busy={busy || restoring}
        onUndo={() => void ask('undo', [exchange.answer!.evidence.scene.doc_id || exchange.answer!.doc_ids[0]])} onOpenItem={(id) => void openCommandItem(exchange.answer!, id)} onOpenCitation={(citation) => {
        setViewer((previous) => ({ answer: exchange.answer!, citation, request: (previous?.request ?? 0) + 1, mode: '2d' }))
        onOpenCitation(citation)
      }} onVisualise={(citation) => {
        setViewer((previous) => ({ answer: exchange.answer!, citation, request: (previous?.request ?? 0) + 1, mode: '3d' }))
        onOpenCitation(citation)
      }} /> : <article className="exchange" key={`${exchange.id}-${index}`}>
        {exchange.question && <div className="question-bubble">{exchange.question}</div>}
        {exchange.content ? <p className="answer-text">{exchange.content}</p>
          : <p className="error-message" role="alert">{NO_ANSWER_MESSAGE}{exchange.question && <button type="button" className="button button-raised retry-button" disabled={busy || restoring} onClick={() => void ask(exchange.question)}>Retry</button>}</p>}
      </article>)}
      {failed && !busy && <article className="exchange failed-exchange" data-testid="failed-exchange">
        <div className="question-bubble">{failed.question}</div>
        <p className="error-message" role="alert">{error}<button type="button" className="button button-raised retry-button" onClick={() => void ask(failed.question, failed.docIds)}>Retry</button></p>
      </article>}
      {busy && <div className="exchange pending-exchange" aria-busy="true">
        <div className="question-bubble">{pendingQuestion}</div>
        {statuses.length > 1 && <ul className="status-trail" aria-label="Steps so far">{statuses.slice(0, -1).map((text, index) => <li key={`${index}-${text}`}>{text}</li>)}</ul>}
        <div className="status-lines" role="status" aria-live="polite"><span className="thinking-mark" aria-hidden="true">S</span><ThinkingText text={statuses.at(-1) || 'Thinking…'} /></div>
        {!!streamText && <p className="answer-text streaming-text" data-testid="streaming-answer">{streamText.replace(/\*\*/g, '').replace(/(^|\s)_([^_\n]+)_(?=\s|$)/g, '$1$2')}</p>}
        <div className="answer-skeleton" data-testid="answer-skeleton" aria-hidden="true">
          {streamText.length < 60 && <><span className="skeleton-line" style={{ width: '62%' }} /><span className="skeleton-line" style={{ width: '88%' }} /><span className="skeleton-line" style={{ width: '74%' }} /></>}
          <div className="skeleton-card"><span className="skeleton-line" style={{ width: '22%' }} /><span className="skeleton-line" style={{ width: '80%' }} /><span className="skeleton-line" style={{ width: '56%' }} /></div>
        </div>
        {!!traces.length && <details className="answer-detail"><summary>Show thought process</summary>{traces.map((trace, index) => <p key={index}>{trace.detail}</p>)}</details>}
      </div>}
    </div>
    <div className="composer-area" ref={composerArea}>
      {error && !failed && <p className="error-message" role="alert">{error}</p>}
      {needDoc && !selected.length && <div className="need-document" role="alert" data-testid="need-document">
        <strong>Add a drawing first</strong>
        <span>This question needs a drawing or model to read. Your text is kept.</span>
        <div className="need-document-actions">
          <Button variant="raised" onClick={() => { setNeedDoc(false); const at = draft.endsWith(' ') || !draft ? '@' : ' @'; const next = draft + at; setDraft(next); textarea.current?.focus(); updateMention(next, next.length) }}>Choose a document</Button>
          <Button variant="raised" onClick={() => { try { sessionStorage.setItem('hologram.open-upload', '1') } catch { /* optional */ } window.location.hash = '/data' }}>Upload</Button>
        </div>
      </div>}
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
          <button type="button" className="composer-document-option" disabled={demo} onClick={() => openUpload()}><Upload size={16} />Upload a drawing<small>PDF, PNG, JPG, DXF, IFC</small></button>
          <button type="button" className="composer-document-option" disabled={loadingDocs || !docs.length} onClick={() => {
            const next = draft + (draft && !/\s$/.test(draft) ? ' @' : '@')
            setToolsOpen(false); setDraft(next); updateMention(next, next.length); textarea.current?.focus()
          }}><FolderOpen size={16} />Include a document<AtSign size={13} /></button>
          <p className="picker-heading">Skills</p>
          <SkillPicker disabled={busy || restoring || hidden} onPick={(prompt) => { setDraft(prompt); setMention(null); setToolsOpen(false); textarea.current?.focus() }} />
        </div>}
        <div className="composer-actions"><button ref={toolsButton} className="document-context" aria-label="Add to question" aria-haspopup="dialog" aria-expanded={toolsOpen} aria-controls={toolsOpen ? 'composer-tools' : undefined} title="Add documents or skills" type="button" disabled={busy || restoring || hidden} onClick={() => { setMention(null); setToolsOpen((open) => !open) }}><Plus size={16} /></button><button className="document-context composer-upload" aria-label="Upload a drawing" title="Upload a drawing" type="button" disabled={busy || restoring || hidden || demo} onClick={() => openUpload()}><Paperclip size={16} /></button><MicButton disabled={busy || restoring || hidden} onInterim={(text) => setDraft(text)} onText={(text) => { setDraft(text); setMention(null); textarea.current?.focus() }} />
          <Button type="submit" variant="primary" className="send-button" aria-label="Send question" disabled={!draft.trim() || busy || restoring || !docs.length || !!mention}><ArrowUp size={18} /></Button>
        </div>
      </form>
      <p className="composer-disclaimer">AI can make mistakes. Verify important information.</p>
    </div>
    <UploadDialog open={uploadOpen} initialFile={droppedFile} onClose={() => { setUploadOpen(false); setDroppedFile(null) }}
      onAsk={(doc) => { attachDocument(doc); textarea.current?.focus() }}
      onOpen={(doc) => attachDocument(doc)}
      onReady={(doc) => { attachDocument(doc); void onRefresh?.().catch(() => undefined) }} />
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
        <DocumentViewer key={viewer.citation.doc_id} answer={viewer.answer} citation={viewer.citation} sheet={sheet} initialMode={viewer.mode} openRequest={viewer.request}
          chatId={liveChatId}
          edits={sceneEdits[viewer.citation.doc_id]} commands={viewerCommands.length ? viewerCommands : undefined} onClose={() => setViewer(null)} />
      </DrawingEditsContext>
    </>}
  </div></>
}
