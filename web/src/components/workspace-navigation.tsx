import { ChartNoAxesCombined, Check, Database, GitCompare, House, BotMessageSquare, MoreHorizontal, Library, Inbox, Wrench, CircleHelp } from 'lucide-react'
import { Tooltip } from './ui/tooltip'
import { Button } from './ui'
import type { Route } from '../lib/router'
import type { KeyboardEvent } from 'react'
import './help-navigation.css'

/** Data owns the upload session, including refresh and the ready-document actions. */
export function UploadAction({ children = 'Upload' }: { children?: string }) {
  return <Button variant="raised" onClick={() => { window.location.hash = '/data?upload=1' }}>{children}</Button>
}

export const navigation = [
  { route: 'overview', label: 'Overview', icon: House },
  { route: 'chat', label: 'Chat', icon: BotMessageSquare },
  { route: 'changes', label: 'Changes', icon: Inbox },
  { route: 'data', label: 'Data', icon: Database },
  { route: 'compare', label: 'Compare', icon: GitCompare },
  { route: 'library', label: 'Library', icon: Library },
  { route: 'tools', label: 'Tools', icon: Wrench },
  { route: 'accuracy', label: 'Accuracy', icon: ChartNoAxesCombined },
] as const

/** Pages that stay reachable by URL (Library and Tools now hold them) but have no nav entry. */
const hiddenPages = { skills: 'Skills', automations: 'Automations', findings: 'Findings', help: 'Help' } as const
const morePages = [...navigation.slice(4), { route: 'help', label: 'Help', icon: CircleHelp }] as const
export function pageLabel(route: Route): string {
  return navigation.find((item) => item.route === route)?.label ?? hiddenPages[route as keyof typeof hiddenPages]
}

export function ProjectSwitcher() {
  return <div className="project-switcher" aria-label="Project: Construction project">
    <span className="project-mark" aria-hidden="true">D</span>
    <span className="project-name">Construction project</span>
  </div>
}

function closeMore(event: KeyboardEvent<HTMLDetailsElement>) {
  if (event.key === 'Escape' && event.currentTarget.open) {
    event.preventDefault()
    event.stopPropagation()
    event.currentTarget.open = false
    event.currentTarget.querySelector('summary')?.focus()
  }
}

export function WorkspaceNavigation({ route }: { route: Route }) {
  return <>
    <aside className="rail" aria-label="Workspace sidebar">
      <a href="#/overview" className="brand-mark" aria-label="Hologram home">Hologram</a>
      <ProjectSwitcher />
      <nav aria-label="Workspace navigation">
        {[navigation[0], navigation[1], navigation[4], navigation[2], navigation[5], navigation[3], navigation[6]].map(({ route: destination, label, icon: Icon }) => <Tooltip content={label} key={destination}>
          <a href={`#/${destination}`} className={`rail-item ${route === destination ? 'active' : ''}`} aria-label={label} aria-current={route === destination ? 'page' : undefined}>
            <Icon size={20} /><span>{label}</span>
          </a>
        </Tooltip>)}
        <details className="help-more" key={route} onKeyDown={closeMore}>
          <summary className={`rail-item ${morePages.some((item) => item.route === route) ? 'active' : ''}`} aria-label="More"><MoreHorizontal size={20} /></summary>
          <div className="help-more-menu">{morePages.map(({ route: destination, label, icon: Icon }) => <a key={destination} href={`#/${destination}`} aria-current={route === destination ? 'page' : undefined}><Icon size={18} /><span>{label}</span>{route === destination && <Check size={15} />}</a>)}</div>
        </details>
      </nav>
      <div className="workspace-footer"><span className="workspace-avatar" aria-hidden="true">AK</span><span>Shared workspace<small>No account needed</small></span></div>
    </aside>
    <nav className="mobile-navigation" aria-label="Mobile navigation">
      {navigation.slice(0, 4).map(({ route: destination, label, icon: Icon }) => <a key={destination} href={`#/${destination}`} aria-current={route === destination ? 'page' : undefined}><Icon size={19} /><span>{label}</span></a>)}
      <details className="mobile-more" key={route} onKeyDown={closeMore}>
        <summary aria-label="More pages" className={morePages.some((item) => item.route === route) ? 'active' : ''}><MoreHorizontal size={19} /><span>More</span></summary>
        <div className="more-menu">{morePages.map(({ route: destination, label, icon: Icon }) => <a key={destination} href={`#/${destination}`} aria-current={route === destination ? 'page' : undefined}><Icon size={18} /><span>{label}</span>{route === destination && <Check size={15} />}</a>)}</div>
      </details>
    </nav>
  </>
}
