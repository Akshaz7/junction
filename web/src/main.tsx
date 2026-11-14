import { StrictMode, useState } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import ViewerTestPage from './viewer3d/ViewerTestPage'
import { MicButton, SpeakButton } from './components/voice-controls'
import './styles/app.css'
import './styles/touch.css'
import './styles/accessibility.css'

// Dev routes for component tests (3D viewer T-01/T-02, voice W-14); wired by the LEAD.
const testRoute = () => window.location.hash.replace(/^#\/?/, '')
const isTestRoute = () => ['viewer-test', 'voice-test'].includes(testRoute())

function VoiceTestPage() {
  const [draft, setDraft] = useState('')
  return <main>
    <SpeakButton text="There are 11 windows." />
    <MicButton onText={setDraft} />
    <input aria-label="Voice transcript" value={draft} onChange={(event) => setDraft(event.target.value)} />
  </main>
}

function Root() {
  const route = testRoute()
  if (route === 'viewer-test') return <ViewerTestPage />
  if (route === 'voice-test') return <VoiceTestPage />
  return <App />
}

window.addEventListener('hashchange', () => {
  const key = isTestRoute() ? testRoute() : 'app'
  if (key !== document.body.dataset.testRoute) window.location.reload()
})
document.body.dataset.testRoute = isTestRoute() ? testRoute() : 'app'
document.body.dataset.viewerTest = testRoute() === 'viewer-test' ? '1' : '0'

createRoot(document.getElementById('root')!).render(<StrictMode><Root /></StrictMode>)
