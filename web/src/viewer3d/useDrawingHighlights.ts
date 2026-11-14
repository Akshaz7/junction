import { useEffect, useMemo, useState } from 'react';
import { createLiveHighlightClient } from './liveHighlight';
import { setHover, setSelected } from './link';

/** Clear evidence in both views through the persisted chat command layer. */
export function useDrawingHighlights(docId: string, answerId: string, chatId?: string | null) {
  const [cleared, setCleared] = useState(false);
  const channel = useMemo(() => createLiveHighlightClient({ chat_id: chatId ?? undefined }), [chatId]);
  useEffect(() => { setCleared(false); }, [docId, answerId]);
  useEffect(() => channel.onSceneEvent((event) => {
    if (event.doc_id !== docId) return;
    if (event.type === 'scene.state') setCleared(event.highlighted.length === 0);
    else if (event.op === 'highlight' || event.op === 'isolate') setCleared(event.item_ids.length === 0);
    else if (event.op === 'reset') setCleared(true);
  }), [channel, docId]);
  return { cleared, clear() {
    setCleared(true);
    setHover(null, '2d'); setHover(null, '3d'); setSelected(null, '2d');
    channel.sendCommand(docId, { op: 'highlight', item_ids: [] });
  } };
}
