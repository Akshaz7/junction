// Development-only entry for exercising the actual viewer against an isolated API.
import { createRoot } from 'react-dom/client'
import { DocumentViewer } from '../src/components/document-viewer'
import { ExportAnswerButton } from '../src/components/answer-export'
import type { Answer, Document } from '../src/lib/types'
import '../src/styles/tokens.css'
import '../src/styles/app.css'
const doc: Document = { doc_id: 'sheet-under-test', title: 'Ventilation sheet — markup verification', source: 'Private evaluation', formats: ['png'], kind: 'raster', pages: 2, licence: 'Private evaluation only', credit: 'Judge-supplied sheet', heldout: false }
const answer: Answer = { answer_id: 'markup-browser', question: 'Review this drawing', doc_ids: [doc.doc_id], answer: { text_md: 'Review saved symbols and site notes.', value: null, unit: null, confidence: 0, abstained: false }, citations: [{ n: 1, doc_id: doc.doc_id, page: 1, kind: 'region', bbox_px: null, item_ids: [], quote: null }], evidence: { boxes: [], scene: { doc_id: doc.doc_id, highlight_item_ids: [], camera_target_item_id: null } }, trace: [], route: 'index', cost: { usd_total: 0, calls: [] }, latency_ms: 0 }
createRoot(document.getElementById('root')!).render(<main style={{ height: '100dvh', display: 'flex', flexDirection: 'column' }}><ExportAnswerButton answer={answer} docs={[doc]} /><DocumentViewer answer={answer} citation={answer.citations[0]} sheet={false} onClose={() => {}} /></main>)
