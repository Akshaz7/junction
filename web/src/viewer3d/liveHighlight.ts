import { applyCommand, applyState, emptyCommandState, type SceneCommand, type SceneSnapshot } from './commands';
import { decodeAdvisorEvent, type AdvisorEvent } from './advisor';
import { liveSocketUrl } from '../lib/live-url';

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

export type SceneEvent =
  | (SceneCommand & { type: 'scene.edit'; doc_id: string; edit_id?: string; chat_id?: string })
  | (SceneSnapshot & { type: 'scene.state'; doc_id: string; chat_id?: string });
export interface SceneChannel extends HighlightChannel {
  onSceneEvent(callback: (event: SceneEvent) => void): () => void;
  sendCommand(doc_id: string, command: SceneCommand): void;
}
export interface FindingsUpdated { type: 'findings.updated'; doc_id: string; count: number }
type LiveMessage = HighlightMessage | SceneEvent | AdvisorEvent | FindingsUpdated | { type: 'ping' };

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
  if (value.type === 'advisor.cards') return decodeAdvisorEvent(value);
  if (value.type === 'findings.updated') return typeof value.doc_id === 'string' && !!value.doc_id
    && Number.isInteger(value.count) && (value.count as number) >= 0 ? value as unknown as FindingsUpdated : null;
  const ids = (v: unknown): v is string[] => Array.isArray(v) && v.every((id) => typeof id === 'string' && id.length > 0);
  const labels = (v: unknown) => record(v) && Object.values(v).every((label) => typeof label === 'string');
  if ((value.type === 'scene.edit' || value.type === 'scene.state') && typeof value.doc_id === 'string' && value.doc_id) {
    if (value.type === 'scene.edit') {
      if (!['highlight', 'hide', 'restore', 'reset', 'isolate'].includes(value.op as string) || !ids(value.item_ids)
        || (value.labels !== undefined && !labels(value.labels))
        || (value.edit_id !== undefined && typeof value.edit_id !== 'string')) return null;
    } else if (!ids(value.hidden) || !ids(value.highlighted) || !labels(value.labels)
      || (value.isolated != null && !ids(value.isolated))) return null;
    return value as unknown as SceneEvent;
  }
  if (value.type !== 'scene.highlight' || typeof value.doc_id !== 'string' || !value.doc_id
    || !Array.isArray(value.item_ids) || !value.item_ids.every((id) => typeof id === 'string' && id.length > 0)) return null;
  if (value.labels !== undefined && (!record(value.labels)
    || !Object.values(value.labels).every((label) => typeof label === 'string'))) return null;
  const item_ids = [...new Set(value.item_ids as string[])];
  const labelMap = value.labels as Record<string, string> | undefined;
  return {
    type: 'scene.highlight', doc_id: value.doc_id, item_ids,
    ...(labelMap ? { labels: Object.fromEntries(item_ids.filter((id) => Object.hasOwn(labelMap, id)).map((id) => [id, labelMap[id]])) } : {}),
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
} = {}): SceneChannel & {
  onAdvisorCards(callback: (event: AdvisorEvent) => void): () => void;
  onFindingsUpdated(callback: (event: FindingsUpdated) => void): () => void;
} {
  const listeners = new Set<(event: HighlightMessage) => void>();
  const sceneListeners = new Set<(event: SceneEvent) => void>();
  const advisorListeners = new Set<(event: AdvisorEvent) => void>();
  const findingsListeners = new Set<(event: FindingsUpdated) => void>();
  const sceneStates = new Map<string, SceneEvent & { type: 'scene.state' }>();
  const editIds = new Set<string>();
  const commandQueue: SceneEvent[] = [];
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
    if (retry !== undefined || (!listeners.size && !sceneListeners.size && !advisorListeners.size && !findingsListeners.size && !pending.size && !commandQueue.length)) return;
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
    while (commandQueue.length) {
      try { socket.send(JSON.stringify(commandQueue[0])); commandQueue.shift(); }
      catch { socket.close(); return; }
    }
  }

  function deliverScene(event: SceneEvent) {
    if (event.type === 'scene.edit' && event.edit_id) {
      if (editIds.has(event.edit_id)) return;
      editIds.add(event.edit_id);
      if (editIds.size > 2000) editIds.delete(editIds.values().next().value!);
    }
    const previous = sceneStates.get(event.doc_id);
    const state = event.type === 'scene.state' ? applyState(event)
      : applyCommand(previous ? applyState(previous) : emptyCommandState(), event);
    // Preserve omitted labels so a later viewer can resolve them from its manifest tags.
    const suppliedLabels = event.type === 'scene.state' || event.op === 'highlight' || event.op === 'isolate'
      ? event.labels ?? {} : previous?.labels ?? {};
    sceneStates.set(event.doc_id, {
      type: 'scene.state', doc_id: event.doc_id, hidden: [...state.hidden],
      highlighted: [...state.highlighted.keys()], labels: Object.fromEntries([...state.highlighted.keys()]
        .filter((id) => Object.hasOwn(suppliedLabels, id)).map((id) => [id, suppliedLabels[id]])),
      isolated: state.isolated === null ? null : [...state.isolated],
    });
    for (const callback of sceneListeners) callback(event);
  }

  function release() {
    if (listeners.size || sceneListeners.size || advisorListeners.size || findingsListeners.size) return;
    if (retry !== undefined) clearTimeout(retry);
    retry = undefined;
    const previous = socket;
    socket = null;
    previous?.close();
    latest.clear(); pending.clear(); sceneStates.clear(); editIds.clear(); commandQueue.length = 0;
    attempt = 0;
  }

  function connect() {
    if (socket || retry !== undefined) return;
    try {
      const url = options.url ?? liveSocketUrl();
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
        } else if (event?.type === 'advisor.cards') {
          for (const callback of advisorListeners) callback(event);
        } else if (event?.type === 'findings.updated') {
          for (const callback of findingsListeners) callback(event);
        } else if (event?.type === 'scene.edit' || event?.type === 'scene.state') {
          deliverScene(event);
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
    onFindingsUpdated(callback) {
      findingsListeners.add(callback);
      connect();
      return () => { findingsListeners.delete(callback); release(); };
    },
    onAdvisorCards(callback) {
      advisorListeners.add(callback);
      connect();
      return () => { advisorListeners.delete(callback); release(); };
    },
    onHighlight(callback) {
      listeners.add(callback);
      for (const event of latest.values()) callback(event);
      connect();
      return () => {
        listeners.delete(callback);
        release();
      };
    },
    onSceneEvent(callback) {
      sceneListeners.add(callback);
      for (const event of sceneStates.values()) callback(event);
      connect();
      return () => { sceneListeners.delete(callback); release(); };
    },
    sendCommand(doc_id, command) {
      const event: SceneEvent = { ...command, type: 'scene.edit', doc_id, edit_id: crypto.randomUUID() };
      deliverScene(event);
      commandQueue.push(event);
      connect(); flush();
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
export const onSceneEvent = shared.onSceneEvent;
export const sendCommand = shared.sendCommand;
export const onAdvisorCards = shared.onAdvisorCards;
export const onFindingsUpdated = shared.onFindingsUpdated;
