# T-03 2D wiring (from 3D worker, apply after W-18) — web/src/components/document-viewer.tsx
Add import/hook/effects inside DocumentViewer after its state declarations; add attributes to each numbered evidence <g>, replacing its className. Reverse selection uses existing active/focusBox. Desktop "Visualise it" from the drawing viewer opens a nonmodal 3D panel alongside. e2e opts in with ?viewer3dTest=1, calls canvas.__viewer3d.pick(item_id); state() returns highlight ids/labels.

```tsx
import { setHover, setSelected, useLinkedItem } from '../viewer3d'
const linked = useLinkedItem()
useEffect(() => { if (linked.selectedSource !== '3d') return; const i = regions.findIndex(r => r.id === linked.selected); if (i >= 0) setActive(i) }, [linked.selected, linked.selectedSource, regions])
useEffect(() => { setHover(null, '2d'); setSelected(null, '2d'); return () => { setHover(null, '2d'); setSelected(null, '2d') } }, [citation.doc_id, citation.page])
data-item-id={region.id} data-linked={linked.selected === region.id || linked.hovered === region.id ? 'true' : undefined}
onPointerDown={event => event.stopPropagation()}
onMouseEnter={() => setHover(region.id, '2d')} onMouseLeave={() => setHover(null, '2d')}
onClick={() => { setActive(index); setSelected(region.id, '2d') }}
className={`evidence-region ${region.text ? 'text-highlight' : ''} ${index === active || linked.selected === region.id || linked.hovered === region.id ? 'is-active' : ''}`}
```
