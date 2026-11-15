import { ArrowRight, Box, Boxes, GitCompare, Calculator, FileStack, MessageSquareText, ScanSearch, ShieldCheck, Smartphone } from 'lucide-react'
import type { Document } from '../lib/types'
import './overview-screen.css'

const capabilities = [
  { title: 'Ask in plain English', detail: 'Every answer comes with cited proof.', icon: MessageSquareText, href: '#/chat' },
  { title: 'Numbered boxes', detail: 'Items marked on the drawing itself.', icon: ScanSearch, href: '#/chat' },
  { title: '3D from a plan', detail: 'Visualise it; the same items glow.', icon: Box, href: '#/chat' },
  { title: 'AR on iPhone', detail: 'Show it on the table, walk it 1:1.', icon: Smartphone, href: '#/help' },
  { title: 'Projects and graph', detail: 'Many files, one knowledge graph.', icon: Boxes, href: '#/projects' },
  { title: 'Compare revisions', detail: 'See what changed between versions.', icon: GitCompare, href: '#/compare' },
  { title: 'Step-by-step maths', detail: 'Quantities with the calculation shown.', icon: Calculator, href: '#/chat' },
  { title: 'Code checks', detail: 'Fire and access rules with sources.', icon: ShieldCheck, href: '#/tools' },
] as const

export function OverviewScreen({ docs = [] }: { docs?: Document[] }) {
  return <section className="overview-screen" aria-label="Workspace overview">
    <div className="overview-hero">
      <p className="overview-eyebrow"><FileStack size={14} aria-hidden /> PDF, DXF, IFC and scans{docs.length ? ` · ${docs.length} in your library` : ''}</p>
      <h2>Stoa Pro: ask your drawings anything</h2>
      <p className="overview-lede">Read every drawing and model once, then get exact answers you can check on the plan, in 3D and in AR.</p>
      <a className="overview-cta" href="#/chat">Start a chat <ArrowRight size={16} aria-hidden /></a>
    </div>
    <ul className="overview-caps" aria-label="What Stoa Pro does">
      {capabilities.map(({ title, detail, icon: Icon, href }) => <li key={title}><a href={href}><Icon size={20} aria-hidden /><strong>{title}</strong><span>{detail}</span></a></li>)}
    </ul>
  </section>
}
