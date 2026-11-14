import { useState } from 'react'
import { Clock3, Library } from 'lucide-react'
import { SkillsScreen } from './skills-screen'
import { AutomationsScreen } from './automations-screen'
import type { Document } from '../lib/types'
import './library-screen.css'

/** Library: saved skills and starter prompts, and recurring automations, from the live skills/automations API. */
export function LibraryScreen({ docs }: { docs: Document[] }) {
  const [tab, setTab] = useState<'skills' | 'automations'>('skills')
  return <div className="library-screen" aria-label="Library">
    <div className="library-tabs" role="tablist" aria-label="Library sections">
      <button type="button" role="tab" aria-selected={tab === 'skills'} onClick={() => setTab('skills')}><Library size={15} />Skills</button>
      <button type="button" role="tab" aria-selected={tab === 'automations'} onClick={() => setTab('automations')}><Clock3 size={15} />Automations</button>
    </div>
    <div className="library-body" role="tabpanel">{tab === 'skills' ? <SkillsScreen docs={docs} /> : <AutomationsScreen docs={docs} />}</div>
  </div>
}
