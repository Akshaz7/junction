import { onHighlight, sameHighlight, sendHighlight, type HighlightChannel, type HighlightMessage } from './liveHighlight';
import type { Viewer } from './viewer';

/** Keep WebSocket details outside the renderer. Subscribe while geometry is loading. */
export function bindLiveHighlight(
  viewer: Pick<Viewer, 'scene' | 'highlight' | 'getHighlightState' | 'onHighlightChange'>,
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
    try { viewer.highlight(event.item_ids, { labels: event.labels }); }
    finally { applyingRemote = false; }
  }

  const unsubscribe = channel.onHighlight((event) => {
    if (!viewer.scene) pending.set(event.doc_id, event);
    else apply(event);
  });
  const unsubscribeViewer = viewer.onHighlightChange((state) => {
    const doc = currentDoc();
    if (!applyingRemote && doc) channel.sendHighlight(doc, state.highlighted, state.labels);
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
