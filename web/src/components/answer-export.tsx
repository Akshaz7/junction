import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Copy, FileDown, LoaderCircle, Printer, X } from 'lucide-react'
import { workspaceApi } from '../lib/api'
import type { Answer, Document } from '../lib/types'
import { buildAnswerReport, buildChatReport, drawReportPage, reportCrop, reportToHtml, reportToMarkdown, type AnswerReport, type ReportDrawing, type ReportPage } from '../lib/answer-export'
import reportStyles from './answer-export.css?inline'
import './answer-export.css'

export interface ExportAnswerButtonProps {
  answer: Answer
  docs: Document[]
  chatId?: string | null
  /** Mark reports from an offline/demo answer even if the answer has no stub trace. */
  demo?: boolean
}

async function renderDrawing(page: ReportPage, signal: AbortSignal): Promise<ReportDrawing> {
  const blob = await workspaceApi.getPageImage(page.source.docId, page.page, signal)
  signal.throwIfAborted()
  const url = URL.createObjectURL(blob)
  const image = new Image()
  try {
    await new Promise<void>((resolve, reject) => {
      const abort = () => finish(signal.reason ?? new Error('Drawing export cancelled.'))
      signal.addEventListener('abort', abort, { once: true })
      const finish = (error?: unknown) => {
        signal.removeEventListener('abort', abort)
        image.onload = null; image.onerror = null
        if (error) reject(error); else resolve()
      }
      image.onload = () => finish()
      image.onerror = () => finish(new Error('The drawing image could not be decoded.'))
      image.src = url
      if (signal.aborted) abort()
    })
    signal.throwIfAborted()
    const canvas = document.createElement('canvas')
    try {
      const dataUrl = drawReportPage(image, image.naturalWidth, image.naturalHeight, page.regions, canvas)
      const valid = reportCrop(page.regions, image.naturalWidth, image.naturalHeight).regions.length
      const notice = !valid ? 'No 2D boxes supplied within this image; showing the original page without highlights.'
        : valid < page.regions.length ? 'Some evidence boxes fall outside the drawing and could not be shown.' : undefined
      return { dataUrl, notice }
    } finally { canvas.width = 0; canvas.height = 0 }
  } finally { image.src = ''; URL.revokeObjectURL(url) }
}

function ExportDialog({ answer, docs, chatId, demo, onClose }: ExportAnswerButtonProps & { onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const frame = useRef<HTMLIFrameElement>(null)
  const [scope, setScope] = useState<'answer' | 'chat'>('answer')
  const [prepared, setPrepared] = useState<{ report: AnswerReport; html: string } | null>(null)
  const [loading, setLoading] = useState(true)
  const [frameReady, setFrameReady] = useState(false)
  const [error, setError] = useState('')
  const [status, setStatus] = useState('')
  const [manualCopy, setManualCopy] = useState(false)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const element = dialog.current
    element?.showModal()
    return () => element?.close()
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setPrepared(null); setFrameReady(false); setError(''); setStatus(''); setManualCopy(false)
    async function prepare() {
      const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(20_000)])
      const chat = scope === 'chat' && chatId ? await workspaceApi.getChat(chatId, signal) : null
      const answers = chat ? chat.messages.flatMap((message) => message.answer ? [message.answer] : []) : [answer]
      const ids = [...new Set(answers.flatMap((item) => [...item.doc_ids, ...item.citations.map((citation) => citation.doc_id), item.evidence.scene.doc_id]).filter(Boolean))]
      const metadata = [...docs]
      await Promise.all(ids.filter((id) => !metadata.some((doc) => doc.doc_id === id)).map(async (id) => {
        // Missing source metadata stays explicitly marked, never fabricated.
        try {
          const response = await fetch(`/api/docs/${encodeURIComponent(id)}`, { signal })
          if (response.ok) metadata.push(await response.json() as Document)
        } catch { signal.throwIfAborted() }
      }))
      signal.throwIfAborted()
      const options = { chatId: chatId ?? undefined, baseUrl: window.location.origin, demo: demo || workspaceApi.isDemo }
      const report = chat ? buildChatReport(chat, metadata, options) : buildAnswerReport(answer, metadata, options)
      const drawings: Record<string, ReportDrawing> = {}
      // One decoded drawing/canvas at a time keeps a whole-chat export usable on a phone.
      for (const page of report.entries.flatMap((entry) => entry.pages)) {
        controller.signal.throwIfAborted()
        try {
          drawings[page.key] = await renderDrawing(page, AbortSignal.any([controller.signal, AbortSignal.timeout(15_000)]))
        } catch {
          controller.signal.throwIfAborted()
          drawings[page.key] = { notice: 'Drawing unavailable; no image evidence included. Open the source drawing to verify this answer.' }
        }
      }
      if (!controller.signal.aborted) setPrepared({ report, html: reportToHtml(report, drawings, reportStyles) })
    }
    void prepare().catch(() => {
      if (!controller.signal.aborted) setError('The report could not be prepared. Please try again.')
    }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [answer, docs, chatId, demo, scope, attempt])

  async function copyMarkdown() {
    if (!prepared) return
    setError(''); setStatus(''); setManualCopy(false)
    try {
      await navigator.clipboard.writeText(reportToMarkdown(prepared.report))
      setStatus('Markdown copied. Drawing links open the original pages; box coordinates are included.')
    } catch { setManualCopy(true); setStatus('Select and copy the Markdown below.') }
  }

  function print() {
    try {
      if (!frameReady || !frame.current?.contentWindow) return
      frame.current.contentWindow.focus()
      frame.current.contentWindow.print()
    } catch { setError('The print dialog could not open. Please try again in your browser.') }
  }

  return createPortal(<dialog ref={dialog} className="answer-export-dialog" aria-labelledby="answer-export-title" onCancel={onClose}>
    <header className="answer-export-header"><div><h2 id="answer-export-title">Export site report</h2><p>Question, answer and drawing evidence.</p></div><button type="button" aria-label="Close export report" onClick={onClose}><X size={18} /></button></header>
    <div className="answer-export-toolbar">
      {chatId && <label>Include<select value={scope} onChange={(event) => setScope(event.target.value as 'answer' | 'chat')}><option value="answer">This answer</option><option value="chat">Whole chat</option></select></label>}
      <button type="button" disabled={loading || !prepared} onClick={() => void copyMarkdown()}><Copy size={15} />Copy as Markdown</button>
      <button type="button" disabled={loading || !prepared || !frameReady} onClick={print}><Printer size={15} />Print / Save PDF</button>
    </div>
    {loading && <p className="answer-export-message" role="status"><LoaderCircle size={16} className="answer-export-spinner" />Preparing report and drawing crops…</p>}
    {error && <p className="answer-export-message" role="alert">{error}{!prepared && <button type="button" onClick={() => setAttempt((value) => value + 1)}>Retry</button>}</p>}
    {status && <p className="answer-export-message" role="status">{status}</p>}
    {manualCopy && prepared && <textarea className="answer-export-markdown" aria-label="Report Markdown to copy" readOnly value={reportToMarkdown(prepared.report)} onFocus={(event) => event.currentTarget.select()} autoFocus />}
    {prepared && <iframe ref={frame} className="answer-export-preview" title="Site report preview" srcDoc={prepared.html} onLoad={() => setFrameReady(true)} />}
  </dialog>, document.body)
}

/** Mount beside an answer's existing actions; no changes to the answer card are needed. */
export function ExportAnswerButton(props: ExportAnswerButtonProps) {
  const [open, setOpen] = useState(false)
  const trigger = useRef<HTMLButtonElement>(null)
  const close = () => { setOpen(false); requestAnimationFrame(() => trigger.current?.focus()) }
  return <><button ref={trigger} type="button" className="answer-export-button" onClick={() => setOpen(true)}><FileDown size={15} aria-hidden="true" /><span>Export report</span></button>{open && <ExportDialog {...props} onClose={close} />}</>
}
