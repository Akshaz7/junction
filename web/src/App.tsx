import { useCallback, useEffect, useState } from 'react'
import { Bell, ChevronDown, ChevronRight, Clock, Folder, MessageSquareShare, Plus } from 'lucide-react'
import { Badge, Button } from './components/ui'
import { ProjectSwitcher, WorkspaceNavigation, navigation } from './components/workspace-navigation'
import { PlaceholderPage } from './components/placeholder-page'
import { ChatScreen } from './components/chat-screen'
import { DataScreen } from './components/data-screen'
import { ChangesScreen } from './components/changes-screen'
import { workspaceApi } from './lib/api'
import { navigate, useRoute } from './lib/router'
import type { Citation, Document } from './lib/types'

const ignoreCitation = (_citation: Citation) => {}

export default function App({ onOpenCitation = ignoreCitation }: { onOpenCitation?: (citation: Citation) => void }) {
  const view = useRoute()
  const [docs, setDocs] = useState<Document[]>([])
  const [loadingDocs, setLoadingDocs] = useState(true)
  const [demo, setDemo] = useState(workspaceApi.isDemo)
  const [error, setError] = useState('')
  const [chatKey, setChatKey] = useState(0)
  const [contextDocument, setContextDocument] = useState<Document | null>(null)

  const refreshDocuments = useCallback(async () => {
    const documents = await workspaceApi.getDocuments()
    setDocs(documents)
    setDemo(workspaceApi.isDemo)
    setError('')
  }, [])

  useEffect(() => {
    let active = true
    workspaceApi.getDocuments().then((documents) => {
      if (active) { setDocs(documents); setDemo(workspaceApi.isDemo) }
    }).catch((err: Error) => { if (active) setError(err.message) })
      .finally(() => { if (active) setLoadingDocs(false) })
    return () => { active = false }
  }, [])

  return <div className={`app-shell route-${view}`}>
    <a href="#main-content" className="skip-link" onClick={(event) => { event.preventDefault(); document.getElementById('main-content')?.focus() }}>Skip to content</a>
    <WorkspaceNavigation route={view} />
    <main className="workspace" id="main-content" tabIndex={-1}>
      <header className="topbar">
        <div className="project-title"><span className="wordmark">Hologram</span><span className="topbar-divider" /><span className="workspace-name">Demo workspace</span><div className="mobile-project"><ProjectSwitcher /></div></div><Bell className="project-bell" size={20} />
        <Badge variant={demo || loadingDocs || error ? 'neutral' : 'success'}>{demo ? 'Local demo' : loadingDocs ? 'Connecting…' : error ? 'Connection unavailable' : 'Connected workspace'}</Badge>
      </header>
      <div className="pagebar">
        <h1>{navigation.find((item) => item.route === view)!.label}</h1>
        {view === 'data' && <span className="documents-breadcrumb"><ChevronRight size={16} /><span><Folder size={14} />Documents<ChevronDown size={12} /></span></span>}
        {view === 'chat' && <div className="chat-header-actions"><Button variant="raised" aria-label="New chat" onClick={() => { setChatKey((previous) => previous + 1); setContextDocument(null) }}><Plus size={16} /><span>New</span></Button><Button variant="raised" onClick={() => document.querySelector('.conversation')?.scrollTo({ top: 0, behavior: 'smooth' })}><Clock size={16} /><span>History</span></Button><Button variant="raised" onClick={() => { if (navigator.share) void navigator.share({ title: 'Hologram', url: window.location.href }).catch(() => {}); else void navigator.clipboard?.writeText(window.location.href) }}><MessageSquareShare size={16} /><span>Share</span></Button></div>}
      </div>
      {error && (view === 'chat' || view === 'data') && <p className="error-message document-error" role="alert">{error}</p>}
      <ChatScreen key={chatKey} docs={docs} loadingDocs={loadingDocs} demo={demo} contextDocument={contextDocument} hidden={view !== 'chat'} onOpenCitation={onOpenCitation} />
      <DataScreen docs={docs} loading={loadingDocs} demo={demo} hidden={view !== 'data'} onRefresh={refreshDocuments} onAsk={(doc) => {
        setContextDocument(doc)
        setChatKey((previous) => previous + 1)
        navigate('chat')
      }} />
      {view === 'changes' && <ChangesScreen docs={docs} demo={demo} />}
      {view !== 'data' && view !== 'chat' && view !== 'changes' ? <PlaceholderPage route={view} /> : null}
    </main>
  </div>
}
