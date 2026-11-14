import { createContext } from 'react'
import type { ChatEdits } from './scene-edits'

/** The drawing and its model consume the same chat-scoped edit layer. */
export const DrawingEditsContext = createContext<ChatEdits['docs']>({})
