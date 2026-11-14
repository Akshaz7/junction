import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import ViewerTestPage from './viewer3d/ViewerTestPage'
import './styles/app.css'

// Dev route for the 3D viewer tests (T-01/T-02); wired by the LEAD.
const isViewerTest = () => window.location.hash.replace(/^#\/?/, '') === 'viewer-test'

function Root() {
  return isViewerTest() ? <ViewerTestPage /> : <App />
}

window.addEventListener('hashchange', () => {
  if (isViewerTest() !== (document.body.dataset.viewerTest === '1')) window.location.reload()
})
document.body.dataset.viewerTest = isViewerTest() ? '1' : '0'

createRoot(document.getElementById('root')!).render(<StrictMode><Root /></StrictMode>)
