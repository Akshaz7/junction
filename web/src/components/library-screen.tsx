import { useId, useState } from 'react'
import { Clock3, Library } from 'lucide-react'
import { SkillsScreen } from './skills-screen'
import { AutomationsScreen } from './automations-screen'
import { UploadAction } from './workspace-navigation'
import type { Document } from '../lib/types'
import './library-screen.css'

/** Library: saved skills and starter prompts, and recurring automations, from the live skills/automations API. */
export function LibraryScreen({ docs }: { docs: Document[] }) {
  const [tab, setTab] = useState<'skills' | 'automations'>('skills')
  const id = useId()
  return <div className="library-screen" aria-label="Library">
    <div className="library-tabs" role="tablist" aria-label="Library sections" onKeyDown={(event) => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
      event.preventDefault()
      const next = event.key === 'Home' ? 'skills' : event.key === 'End' ? 'automations' : tab === 'skills' ? 'automations' : 'skills'
      setTab(next)
      document.getElementById(`${id}-${next}`)?.focus()
    }}>
      <button id={`${id}-skills`} type="button" role="tab" tabIndex={tab === 'skills' ? 0 : -1} aria-controls={`${id}-panel`} aria-selected={tab === 'skills'} onClick={() => setTab('skills')}><Library size={15} />Skills</button>
      <button id={`${id}-automations`} type="button" role="tab" tabIndex={tab === 'automations' ? 0 : -1} aria-controls={`${id}-panel`} aria-selected={tab === 'automations'} onClick={() => setTab('automations')}><Clock3 size={15} />Automations</button>
    </div>
    <div id={`${id}-panel`} className="library-body" role="tabpanel" aria-labelledby={`${id}-${tab}`}>{tab === 'skills' ? <SkillsScreen docs={docs} /> : <>{!docs.length && <div className="library-empty"><p>Upload a drawing to create an automation.</p><UploadAction /></div>}<AutomationsScreen docs={docs} /></>}</div>
  </div>
}
