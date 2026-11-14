import { ArrowRight, ChartNoAxesCombined, Clock3, GitCompareArrows, House, WandSparkles } from 'lucide-react'
import { Badge, Card, Chip } from './ui'
import type { Route } from '../lib/router'

const pages = {
  overview: { icon: House, heading: 'Your project, in one place.', description: 'Find an answer in your drawings, or go straight to the source.', empty: 'Start with your project documents', detail: 'Open Data to see the drawings in this workspace. Ask a question in Chat to find an answer with sources you can check.' },
  changes: { icon: GitCompareArrows, heading: 'Keep track of what changed.', description: 'See what moved between drawing versions, with the evidence beside it.', empty: 'No comparisons to show yet', detail: 'Drawing comparisons will appear here when they are available. Open Data to see the current documents.' },
  accuracy: { icon: ChartNoAxesCombined, heading: 'See how the answers hold up.', description: 'Accuracy and cost, measured against the project’s known answers.', empty: 'No evaluation results to show yet', detail: 'There are no measured accuracy or cost results in this view yet.' },
  skills: { icon: WandSparkles, heading: 'A repeatable way to get work done.', description: 'Keep the questions and steps your team uses again and again.', empty: 'No saved skills yet', detail: 'Saved skills will appear here when they are available. For now, ask a question in Chat.' },
  automations: { icon: Clock3, heading: 'Keep the routine work moving.', description: 'A place for recurring checks on your project documents.', empty: 'No automations set up yet', detail: 'Recurring checks will appear here when they are available.' },
} as const

export function PlaceholderPage({ route }: { route: Exclude<Route, 'chat' | 'data'> }) {
  const page = pages[route]
  const Icon = page.icon
  return <section className="placeholder-page" aria-label={`${route} page`}>
    <div className="placeholder-intro"><Chip>Demo workspace</Chip><h2>{page.heading}</h2><p>{page.description}</p></div>
    <Card className="placeholder-card">
      <span className="placeholder-icon"><Icon size={24} strokeWidth={1.5} /></span>
      <h3>{page.empty}</h3><p>{page.detail}</p>
      <div className="placeholder-actions">
        {route === 'overview' ? <><a className="button button-default button-size-default" href="#/chat">Ask your project<ArrowRight size={16} /></a><a className="button button-outline button-size-default" href="#/data">Open Data</a></> : <Badge>Nothing to show yet</Badge>}
      </div>
    </Card>
  </section>
}
