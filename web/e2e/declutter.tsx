// Development-only fixture. All sample content is generated for demo.
import { useState } from 'react'
import { createRoot } from 'react-dom/client'
import { AnswerCard } from '../src/components/answer-card'
import { demoDocument, makeDemoAnswer } from '../src/mock/handler'
import '../src/styles/tokens.css'
import '../src/styles/app.css'
import '../src/styles/touch.css'
import '../src/styles/accessibility.css'

document.body.style.background = 'var(--background)'

const answer = makeDemoAnswer('How many windows are there?')
answer.cost = { usd_total: 0.0058, calls: [{ model: 'demo', cost_usd: 0.0058 }] }
if (!location.search.includes('legacy')) answer.reasoning = {
  steps: [{ kind: 'found', title: 'Found', text: 'Two windows in the sample plan (generated for demo).', cite: 1 }],
  confidence: { label: 'Estimate', pct: null, reason: 'Generated for demo; verify against your drawing.' },
}
if (location.search.includes('takeoff')) answer.answer.text_md = 'Generated for demo.\n\n| Item | Quantity | Unit | Source |\n|---|---|---|---|\n| Windows | 2 | count | [1] |'
function Fixture() {
  const [action, setAction] = useState('')
  return <main style={{ maxWidth: 720, padding: '24px', margin: '0 auto' }}>
    <AnswerCard answer={answer} docs={[demoDocument]} demo onOpenCitation={() => setAction('citation opened')} onVisualise={() => setAction('3D opened')} onAsk={() => setAction('takeoff requested')} />
    <p role="status">{action}</p>
  </main>
}
createRoot(document.getElementById('root')!).render(<Fixture />)
