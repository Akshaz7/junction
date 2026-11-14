import { onHighlight, sameHighlight, sendHighlight, onSceneEvent, sendCommand, type HighlightChannel, type HighlightMessage, type SceneChannel, type SceneEvent } from './liveHighlight';
import type { Viewer } from './viewer';

/** Keep WebSocket details outside the renderer. Subscribe while geometry is loading. */
export function bindLiveHighlight(
  viewer: Pick<Viewer, 'scene' | 'highlight' | 'getHighlightState' | 'onHighlightChange'> & Partial<Pick<Viewer, 'isApplyingCommand'>>,
  docId?: string,
  channel: HighlightChannel = { onHighlight, sendHighlight },
) {
  const pending = new Map<string, HighlightMessage>();
  let applyingRemote = false;
  const currentDoc = () => docId ?? viewer.scene?.manifest.doc_id;

  function apply(event: HighlightMessage) {
    if (!viewer.scene || event.doc_id !== currentDoc()) return;
    const state = viewer.getHighlightState();
    if (sameHighlight(event, { type: 'scene.highlight', doc_id: event.doc_id, item_ids: state.highlighted, labels: state.labels })) return;
    applyingRemote = true;
    try { viewer.highlight(event.item_ids, { labels: event.labels, cinematic: true }); }
    finally { applyingRemote = false; }
  }

  const unsubscribe = channel.onHighlight((event) => {
    if (!viewer.scene) pending.set(event.doc_id, event);
    else apply(event);
  });
  const unsubscribeViewer = viewer.onHighlightChange((state) => {
    const doc = currentDoc();
    if (!applyingRemote && !viewer.isApplyingCommand?.() && doc) channel.sendHighlight(doc, state.highlighted, state.labels);
  });

  return {
    sceneReady() {
      const doc = currentDoc();
      const event = doc ? pending.get(doc) : undefined;
      pending.clear();
      if (event) apply(event);
    },
    dispose() { unsubscribeViewer(); unsubscribe(); pending.clear(); },
  };
}

/** Ordered commands share T-06's socket. Loading buffers every edit; a snapshot replaces the layer.
 * `chatId` (value or getter): local edits are sent with it, so the server keeps them in the chat's shared
 * edit layer, and another chat's edits on the same document are ignored. */
export function bindLiveCommands(
  viewer: Pick<Viewer, 'scene' | 'applyCommand' | 'applyState' | 'onCommandChange'>,
  docId?: string,
  channel: Pick<SceneChannel, 'onSceneEvent' | 'sendCommand'> = { onSceneEvent, sendCommand },
  chatId?: string | (() => string | undefined),
) {
  const currentChat = () => (typeof chatId === 'function' ? chatId() : chatId) || undefined;
  const pending: SceneEvent[] = [];
  const seen = new Set<string>();
  let applyingRemote = false;
  const currentDoc = () => docId ?? viewer.scene?.manifest.doc_id;
  function apply(event: SceneEvent) {
    if (event.doc_id !== currentDoc()) return;
    const chat = currentChat();
    if (chat && event.chat_id && event.chat_id !== chat) return;
    if (event.type === 'scene.edit' && event.edit_id) {
      if (seen.has(event.edit_id)) return;
      seen.add(event.edit_id);
    }
    applyingRemote = true;
    try {
      if (event.type === 'scene.state') viewer.applyState(event);
      else viewer.applyCommand(event);
    } finally { applyingRemote = false; }
  }
  const stopEvents = channel.onSceneEvent((event) => {
    if (applyingRemote) {
      if (event.type === 'scene.edit' && event.edit_id) seen.add(event.edit_id);
      return;
    }
    if (!viewer.scene) pending.push(event);
    else apply(event);
  });
  const stopViewer = viewer.onCommandChange((command) => {
    const doc = currentDoc();
    if (!applyingRemote && doc) {
      // The shared channel delivers locally too; do not apply our own command twice.
      applyingRemote = true;
      try { const chat = currentChat(); if (chat) channel.sendCommand(doc, command, chat); else channel.sendCommand(doc, command); }
      finally { applyingRemote = false; }
    }
  });
  return {
    sceneReady() { for (const event of pending) apply(event); pending.length = 0; },
    dispose() { stopViewer(); stopEvents(); pending.length = 0; seen.clear(); },
  };
}
