import { useId, useState } from 'react'
import { Clock3, Library } from 'lucide-react'
import { SkillsScreen } from './skills-screen'
import { AutomationsScreen } from './automations-screen'
import { UploadAction } from './workspace-navigation'
import type { Document } from '../lib/types'
import './library-screen.css'

/** Library: saved skills and starter prompts, and recurring automations, from the live skills/automations API. */
export function LibraryScreen({ docs }: { docs: Document[] }) {
  // Automations removed from the demo build (Ash, 2026-11-14): Library shows saved skills only.
  void useState; void useId; void Clock3; void Library; void AutomationsScreen; void UploadAction
  return <div className="library-screen" aria-label="Library"><div className="library-body"><SkillsScreen docs={docs} /></div></div>
}
