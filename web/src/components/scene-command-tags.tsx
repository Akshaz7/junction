import { useState } from 'react'
import { Undo2 } from 'lucide-react'
import type { Answer } from '../lib/types'
import { answerTags, itemIsHidden, type DrawingEdits } from '../lib/scene-edits'
import './scene-command-tags.css'

export function SceneCommandTags({ answer, edits, busy, onUndo, onOpenItem }: {
  answer: Answer; edits?: DrawingEdits; busy?: boolean; onUndo?: () => void; onOpenItem?: (id: string) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const commands = answer.evidence.scene.commands
  if (!commands?.length || answer.answer.abstained) return null
  const tags = answerTags(answer)
  const visible = expanded ? tags : tags.slice(0, 12)
  const canUndo = commands.some((command) => command.op === 'hide' || command.op === 'isolate')
  if (!tags.length && !(canUndo && onUndo)) return null
  return <div className="scene-command-tags" aria-label="Scene command items" data-item-count={tags.length}>
    {visible.map(({ id, tag }) => {
      const hidden = edits ? itemIsHidden(edits, id) : commands.some((command) => command.op === 'hide' && command.item_ids.includes(id))
      return <button type="button" key={id} className={`scene-tag${hidden ? ' is-hidden' : ''}`} data-item-id={id} data-hidden={String(hidden)}
        aria-label={`Show ${edits?.tags[id] ?? tag} on drawing${hidden ? ', hidden' : ''}`} disabled={!onOpenItem} onClick={() => onOpenItem?.(id)}>
        <span>{edits?.tags[id] ?? tag}</span>{hidden && <small>hidden</small>}
      </button>
    })}
    {tags.length > 12 && <button className="scene-tags-more" type="button" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>{expanded ? 'Show fewer' : `+${tags.length - 12} more`}</button>}
    {canUndo && onUndo && <button className="scene-command-undo" type="button" disabled={busy} onClick={onUndo}><Undo2 size={13} />Undo</button>}
  </div>
}
