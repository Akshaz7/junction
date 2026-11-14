import { useEffect, useState } from 'react'
import { ArrowRight, FileText, Plus, Search } from 'lucide-react'
import { Badge, Button, Input } from './components/ui'
import { ProjectSwitcher, WorkspaceNavigation, navigation } from './components/workspace-navigation'
import { PlaceholderPage } from './components/placeholder-page'
import { ChatScreen } from './components/chat-screen'
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
  const [search, setSearch] = useState('')
  const [chatKey, setChatKey] = useState(0)
  const [contextDocument, setContextDocument] = useState<Document | null>(null)

  useEffect(() => {
    let active = true
    workspaceApi.getDocuments().then((documents) => {
      if (active) { setDocs(documents); setDemo(workspaceApi.isDemo) }
    }).catch((err: Error) => { if (active) setError(err.message) })
      .finally(() => { if (active) setLoadingDocs(false) })
    return () => { active = false }
  }, [])

  return <div className="app-shell">
    <a href="#main-content" className="skip-link" onClick={(event) => { event.preventDefault(); document.getElementById('main-content')?.focus() }}>Skip to content</a>
    <WorkspaceNavigation route={view} />
    <main className="workspace" id="main-content" tabIndex={-1}>
      <header className="topbar">
        <div className="project-title"><span className="wordmark">Hologram</span><span className="topbar-divider" /><span className="workspace-name">Demo workspace</span><div className="mobile-project"><ProjectSwitcher /></div></div>
        <Badge variant={demo || loadingDocs || error ? 'neutral' : 'success'}>{demo ? 'Local demo' : loadingDocs ? 'Connecting…' : error ? 'Connection unavailable' : 'Connected workspace'}</Badge>
      </header>
      <div className="pagebar">
        <h1>{navigation.find((item) => item.route === view)!.label}</h1>
        {view === 'chat' && <Button variant="raised" onClick={() => { setChatKey((previous) => previous + 1); setContextDocument(null) }}><Plus size={16} />New chat</Button>}
      </div>
      {error && (view === 'chat' || view === 'data') && <p className="error-message document-error" role="alert">{error}</p>}
      <ChatScreen key={chatKey} docs={docs} loadingDocs={loadingDocs} demo={demo} contextDocument={contextDocument} hidden={view !== 'chat'} onOpenCitation={onOpenCitation} />
      {view === 'data' ? <section className="data-page" aria-label="Project documents">
        <div className="data-header"><div><h2>Project documents</h2><p>The sources behind your answers.</p></div><label className="search-field"><Search size={16} /><Input type="search" aria-label="Search documents" placeholder="Search documents" value={search} onChange={(event) => setSearch(event.target.value)} /></label></div>
        {loadingDocs ? <p role="status">Loading documents…</p> : <div className="document-list">{docs.filter((doc) => doc.title.toLowerCase().includes(search.toLowerCase())).map((doc) => <article className="document-row" key={doc.doc_id}><span className="file-icon"><FileText size={22} /></span><div><h3>{doc.title}</h3><p>{doc.source} · {doc.formats.join(', ').toUpperCase()} · {doc.pages} {doc.pages === 1 ? 'page' : 'pages'}</p><small>{doc.credit} · {doc.licence}</small></div><Button variant="raised" onClick={() => { setContextDocument(doc); navigate('chat') }}>Ask about it<ArrowRight size={15} /></Button></article>)}</div>}
        {!loadingDocs && !docs.filter((doc) => doc.title.toLowerCase().includes(search.toLowerCase())).length && <p className="empty-state">No documents found.</p>}
      </section> : view !== 'chat' ? <PlaceholderPage route={view} /> : null}
    </main>
  </div>
}
