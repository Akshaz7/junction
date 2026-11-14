import { useCallback, useEffect, useState } from 'react'
import { Bell, ChevronDown, ChevronRight, Folder } from 'lucide-react'
import { Badge } from './components/ui'
import { ProjectSwitcher, WorkspaceNavigation, pageLabel } from './components/workspace-navigation'
import { PlaceholderPage } from './components/placeholder-page'
import { AccuracyScreen } from './components/accuracy-screen'
import { FindingsScreen } from './components/findings-screen'
import { SkillsScreen } from './components/skills-screen'
import { AutomationsScreen } from './components/automations-screen'
import { OverviewScreen } from './components/overview-screen'
import { ChatScreen } from './components/chat-screen'
import { ChatHeaderActions } from './components/chat-header-actions'
import { DataScreen } from './components/data-screen'
import { CompareScreen } from './components/compare-screen'
import { LibraryScreen } from './components/library-screen'
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
  const [activeChatId, setActiveChatId] = useState<string | null>(null)
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
        <h1>{pageLabel(view)}</h1>
        {view === 'data' && <span className="documents-breadcrumb"><ChevronRight size={16} /><span><Folder size={14} />Documents<ChevronDown size={12} /></span></span>}
        {view === 'chat' && <ChatHeaderActions chatId={activeChatId} onNew={() => { navigate('chat'); setChatKey((previous) => previous + 1); setContextDocument(null); setActiveChatId(null) }} />}
      </div>
      {error && (view === 'chat' || view === 'data') && <p className="error-message document-error" role="alert">{error}</p>}
      <ChatScreen onChatChange={setActiveChatId} key={chatKey} docs={docs} loadingDocs={loadingDocs} demo={demo} contextDocument={contextDocument} hidden={view !== 'chat'} onOpenCitation={onOpenCitation} />
      <DataScreen docs={docs} loading={loadingDocs} demo={demo} hidden={view !== 'data'} onRefresh={refreshDocuments} onAsk={(doc) => {
        setContextDocument(doc)
        setChatKey((previous) => previous + 1)
        navigate('chat')
      }} />
      {view === 'compare' && <CompareScreen docs={docs} demo={demo} />}
      {view === 'library' && <LibraryScreen docs={docs} />}
      {view === 'tools' && <FindingsScreen docs={docs} />}
      {view === 'changes' && <ChangesScreen docs={docs} demo={demo} />}
      {view === 'accuracy' && <AccuracyScreen />}
      {view === 'findings' && <FindingsScreen docs={docs} />}
      {view === 'skills' && <SkillsScreen docs={docs} />}
      {view === 'automations' && <AutomationsScreen docs={docs} />}
      {view === 'overview' && <OverviewScreen docs={docs} />}
      {view !== 'data' && view !== 'chat' && view !== 'changes' && view !== 'accuracy' && view !== 'overview' && view !== 'findings' && view !== 'skills' && view !== 'automations' && view !== 'compare' && view !== 'library' && view !== 'tools' ? <PlaceholderPage route={view} /> : null}
    </main>
  </div>
}
