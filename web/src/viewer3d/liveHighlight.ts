/** The viewer depends only on these two methods, so W-10 can replace this transport. */
export interface HighlightChannel {
  onHighlight(callback: (event: HighlightMessage) => void): () => void;
  sendHighlight(doc_id: string, item_ids: readonly string[], labels?: Record<string, string>): void;
}

export interface HighlightMessage {
  type: 'scene.highlight';
  doc_id: string;
  item_ids: string[];
  labels?: Record<string, string>;
}

type LiveMessage = HighlightMessage | { type: 'ping' };

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Ignore unrelated events and malformed input without interrupting the socket. */
export function decodeLiveMessage(raw: unknown): LiveMessage | null {
  if (typeof raw !== 'string') return null;
  let value: unknown;
  try { value = JSON.parse(raw); } catch { return null; }
  if (!record(value)) return null;
  if (value.type === 'ping') return { type: 'ping' };
  if (value.type !== 'scene.highlight' || typeof value.doc_id !== 'string' || !value.doc_id
    || !Array.isArray(value.item_ids) || !value.item_ids.every((id) => typeof id === 'string' && id.length > 0)) return null;
  if (value.labels !== undefined && (!record(value.labels)
    || !Object.values(value.labels).every((label) => typeof label === 'string'))) return null;
  const item_ids = [...new Set(value.item_ids as string[])];
  const labels = value.labels as Record<string, string> | undefined;
  return {
    type: 'scene.highlight', doc_id: value.doc_id, item_ids,
    ...(labels ? { labels: Object.fromEntries(item_ids.filter((id) => Object.hasOwn(labels, id)).map((id) => [id, labels[id]])) } : {}),
  };
}

export function encodeHighlight(doc_id: string, item_ids: readonly string[], labels?: Record<string, string>): string {
  return JSON.stringify({ type: 'scene.highlight', doc_id, item_ids, ...(labels ? { labels } : {}) });
}

/** Missing labels mean sequential numbers, exactly as in T-02. Ignore map key order. */
export function sameHighlight(a: HighlightMessage, b: HighlightMessage): boolean {
  const key = (event: HighlightMessage) => JSON.stringify([
    event.doc_id,
    [...new Set(event.item_ids)].map((id, i) => [id, event.labels?.[id] ?? String(i + 1)])
      .sort(([aId], [bId]) => aId.localeCompare(bId)),
  ]);
  return key(a) === key(b);
}

/** Lazy and shared: no socket is created until a consumer subscribes or sends. */
export function createLiveHighlightClient(options: {
  url?: string;
  connect?: (url: string) => WebSocket;
} = {}): HighlightChannel {
  const listeners = new Set<(event: HighlightMessage) => void>();
  const latest = new Map<string, HighlightMessage>();
  // During an outage keep only the newest selection for each document.
  const pending = new Map<string, HighlightMessage>();
  let socket: WebSocket | null = null;
  let retry: ReturnType<typeof setTimeout> | undefined;
  let attempt = 0;

  function deliver(event: HighlightMessage): boolean {
    const previous = latest.get(event.doc_id);
    if (previous && sameHighlight(previous, event)) return false;
    latest.set(event.doc_id, event);
    for (const listener of listeners) listener(event);
    return true;
  }

  function reconnect() {
    if (retry !== undefined || (!listeners.size && !pending.size)) return;
    retry = setTimeout(() => {
      retry = undefined;
      connect();
    }, Math.min(250 * 2 ** Math.min(attempt++, 6), 10_000));
  }

  function flush() {
    if (socket?.readyState !== 1) return;
    for (const [docId, event] of pending) {
      try { socket.send(encodeHighlight(event.doc_id, event.item_ids, event.labels)); }
      catch { socket.close(); return; }
      pending.delete(docId);
    }
  }

  function connect() {
    if (socket || retry !== undefined) return;
    try {
      const url = options.url ?? `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`;
      const connection = (options.connect ?? ((url) => new WebSocket(url)))(url);
      socket = connection;
      connection.addEventListener('open', () => {
        if (socket !== connection) return;
        attempt = 0;
        flush();
      });
      connection.addEventListener('message', (message) => {
        if (socket !== connection) return;
        const event = decodeLiveMessage(message.data);
        if (event?.type === 'ping') {
          if (connection.readyState === 1) connection.send(JSON.stringify({ type: 'pong' }));
        } else if (event) {
          // A newer remote selection supersedes an unsent local selection.
          pending.delete(event.doc_id);
          deliver(event);
        }
      });
      connection.addEventListener('close', () => {
        if (socket !== connection) return;
        socket = null;
        reconnect();
      });
      connection.addEventListener('error', () => { if (socket === connection) connection.close(); });
    } catch { reconnect(); }
  }

  return {
    onHighlight(callback) {
      listeners.add(callback);
      for (const event of latest.values()) callback(event);
      connect();
      return () => {
        listeners.delete(callback);
        if (listeners.size) return;
        if (retry !== undefined) clearTimeout(retry);
        retry = undefined;
        const previous = socket;
        socket = null;
        previous?.close();
        latest.clear();
        pending.clear();
        attempt = 0;
      };
    },
    sendHighlight(doc_id, item_ids, labels) {
      const event = decodeLiveMessage(encodeHighlight(doc_id, item_ids, labels));
      if (!event || event.type !== 'scene.highlight' || !deliver(event)) return;
      pending.set(doc_id, event);
      connect();
      flush();
    },
  };
}

const shared = createLiveHighlightClient();
export const onHighlight = shared.onHighlight;
export const sendHighlight = shared.sendHighlight;
