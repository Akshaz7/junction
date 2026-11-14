import { useEffect, useReducer } from 'react'
import { createLiveHighlightClient, type SceneEvent } from '../viewer3d/liveHighlight'
import { answerSceneEvents, emptyChatEdits, reduceSceneEvent, type ChatEdits } from './scene-edits'
import type { ChatExchange } from './chat-history'

type Action = { type: 'clear' } | { type: 'events'; events: SceneEvent[] }
function reduce(state: ChatEdits, action: Action): ChatEdits {
  return action.type === 'clear' ? emptyChatEdits() : action.events.reduce(reduceSceneEvent, state)
}

/** Join the chat on every connection so reloads/reconnects receive its persisted edit layer. */
export function useSceneEdits(chatId: string | null, exchanges: ChatExchange[], demo: boolean) {
  const [edits, dispatch] = useReducer(reduce, undefined, emptyChatEdits)
  useEffect(() => { dispatch({ type: 'clear' }) }, [chatId])
  useEffect(() => {
    dispatch({ type: 'events', events: exchanges.flatMap((exchange) => exchange.answer ? answerSceneEvents(exchange.answer) : []) })
  }, [chatId, exchanges])
  useEffect(() => {
    if (!chatId || demo) return
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const channel = createLiveHighlightClient({ url: `${protocol}//${window.location.host}/ws?chat_id=${encodeURIComponent(chatId)}` })
    return channel.onSceneEvent((event) => {
      if (event.chat_id && event.chat_id !== chatId) return
      dispatch({ type: 'events', events: [event] })
    })
  }, [chatId, demo])
  return edits.docs
}
