import { useCallback, useEffect, useState } from 'react'
import { ChevronRight, Folder } from 'lucide-react'
import { Badge } from './components/ui'
import { ProjectSwitcher, WorkspaceNavigation, pageLabel } from './components/workspace-navigation'
import { AccuracyScreen } from './components/accuracy-screen'
import { FindingsScreen } from './components/findings-screen'
import { AutomationsScreen } from './components/automations-screen'
import { OverviewScreen } from './components/overview-screen'
import { ChatScreen } from './components/chat-screen'
import { ChatHeaderActions } from './components/chat-header-actions'
import { PairingLanding } from './components/pair-phone'
import { DataScreen } from './components/data-screen'
import { CompareScreen } from './components/compare-screen'
import { ChangesScreen } from './components/changes-screen'
import { HelpScreen } from './components/help-screen'
import { ProjectsScreen } from './components/project-page'
import { ChatCrumb, PanelToggle, ProjectContentPanel, projectLibraryDocs, useChatProject } from './components/project-chat-panel'
import { subscribeApiRetry, workspaceApi } from './lib/api'
import { navigate, useRoute } from './lib/router'
import type { Citation, Document } from './lib/types'

const ignoreCitation = (_citation: Citation) => {}

export default function App({ onOpenCitation = ignoreCitation }: { onOpenCitation?: (citation: Citation) => void }) {
  const view = useRoute()
  const [docs, setDocs] = useState<Document[]>([])
  const [loadingDocs, setLoadingDocs] = useState(true)
  const [demo, setDemo] = useState(workspaceApi.isDemo)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState('')
  useEffect(() => subscribeApiRetry(setRetry), [])
  const [activeChatId, setActiveChatId] = useState<string | null>(null)
  const [chatKey, setChatKey] = useState(0)
  const activeChatTitle = undefined as string | undefined
  const [contextDocument, setContextDocument] = useState<Document | null>(null)
  const chatProject = useChatProject(view === 'chat')
  const [panelOpen, setPanelOpen] = useState(() => window.innerWidth > 800)
  // Narrowing to phone width (rotate, resize) must not leave the content panel covering the chat.
  useEffect(() => {
    const query = window.matchMedia('(max-width: 800px)')
    const onChange = () => { if (query.matches) setPanelOpen(false) }
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [])
  const inProject = !!chatProject.id
  const chatDocs = chatProject.id ? (chatProject.project ? projectLibraryDocs(chatProject.project, docs) : []) : docs

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
    <PairingLanding />
    <WorkspaceNavigation route={view} />
    <main className="workspace" id="main-content" tabIndex={-1}>
      <header className="topbar">
        <div className="project-title"><span className="wordmark"><span className="brand-logo" role="img" aria-label="Stoa" /><span className="brand-pro">Pro</span></span><span className="topbar-divider" /><span className="workspace-name">Demo workspace</span><div className="mobile-project"><ProjectSwitcher /></div></div>
        <Badge variant={demo || loadingDocs || error ? 'neutral' : 'success'}>{demo ? 'Local demo' : loadingDocs ? (retry || 'Connecting…') : error ? 'Connection unavailable' : 'Connected workspace'}</Badge>
      </header>
      <div className={`pagebar${view === 'chat' && inProject ? ' pj-pagebar' : ''}`}>
        <h1>{pageLabel(view)}</h1>
        {view === 'chat' && chatProject.id && <ChatCrumb project={chatProject.project} id={chatProject.id} title={activeChatTitle} />}
        {view === 'data' && <span className="documents-breadcrumb"><ChevronRight size={16} /><span><Folder size={14} />Documents</span></span>}
        {view === 'chat' && <div className="pj-pagebar-right"><ChatHeaderActions chatId={activeChatId} onNew={() => { if (chatProject.id) window.location.hash = `/chat?project=${encodeURIComponent(chatProject.id)}`; else navigate('chat'); setChatKey((previous) => previous + 1); setContextDocument(null); setActiveChatId(null) }} />{chatProject.project && <PanelToggle open={panelOpen} onClick={() => setPanelOpen((open) => !open)} />}</div>}
      </div>
      {error && (view === 'chat' || view === 'data') && <p className="error-message document-error" role="alert">{error}</p>}
      <div className={inProject ? 'chat-with-project' : 'chat-passthrough'}>
        <ChatScreen onChatChange={setActiveChatId} key={chatKey} docs={chatDocs} projectId={chatProject.id} loadingDocs={loadingDocs || (inProject && !chatProject.project && !chatProject.error)} demo={demo} contextDocument={contextDocument} hidden={view !== 'chat'} onRefresh={refreshDocuments} onOpenCitation={onOpenCitation} />
        {view === 'chat' && chatProject.project && panelOpen && <ProjectContentPanel project={chatProject.project} onClose={() => setPanelOpen(false)} />}
      </div>
      <DataScreen docs={docs} loading={loadingDocs} demo={demo} hidden={view !== 'data'} onRefresh={refreshDocuments} onAsk={(doc) => {
        setContextDocument(doc)
        setChatKey((previous) => previous + 1)
        navigate('chat')
      }} />
      {view === 'projects' && <ProjectsScreen docs={docs} />}
      {view === 'compare' && <CompareScreen docs={docs} demo={demo} />}
      {(view === 'library' || view === 'skills') && <OverviewScreen docs={docs} />}
      {view === 'tools' && <FindingsScreen docs={docs} />}
      {view === 'changes' && <ChangesScreen docs={docs} demo={demo} />}
      {view === 'accuracy' && <AccuracyScreen />}
      {view === 'findings' && <FindingsScreen docs={docs} />}
      {view === 'automations' && <AutomationsScreen docs={docs} />}
      {view === 'overview' && <OverviewScreen docs={docs} />}
      {view === 'help' && <HelpScreen />}
    </main>
  </div>
}
