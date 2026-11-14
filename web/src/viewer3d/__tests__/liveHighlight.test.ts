// @vitest-environment node
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  createLiveHighlightClient, decodeLiveMessage, encodeHighlight, sameHighlight,
  type HighlightChannel, type HighlightMessage,
} from '../liveHighlight';
import { bindLiveHighlight } from '../liveViewerHighlight';
import type { HighlightOptions, HighlightState } from '../highlight';
import type { Viewer } from '../viewer';

const selection = (ids = ['window-001', 'window-002'], labels?: Record<string, string>): HighlightMessage => ({
  type: 'scene.highlight', doc_id: 'generated-for-demo', item_ids: ids, ...(labels ? { labels } : {}),
});

class Socket extends EventTarget {
  readyState = 0;
  sent: string[] = [];
  send(data: string) { this.sent.push(data); }
  open() { this.readyState = 1; this.dispatchEvent(new Event('open')); }
  receive(value: unknown) { this.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(value) })); }
  close() { this.readyState = 3; this.dispatchEvent(new Event('close')); }
}

function transport() {
  const sockets: Socket[] = [];
  const connect = vi.fn(() => {
    const socket = new Socket();
    sockets.push(socket);
    return socket as unknown as WebSocket;
  });
  return { sockets, connect, client: createLiveHighlightClient({ url: 'ws://demo/ws', connect }) };
}

afterEach(() => { vi.useRealTimers(); });

describe('live highlight codec', () => {
  it('round trips IDs, custom evidence labels, empty selections, and ping', () => {
    const event = selection(['window-002', 'window-001'], { 'window-001': '12', 'window-002': '7' });
    expect(decodeLiveMessage(encodeHighlight(event.doc_id, event.item_ids, event.labels))).toEqual(event);
    expect(decodeLiveMessage(encodeHighlight(event.doc_id, []))).toEqual(selection([]));
    expect(decodeLiveMessage('{"type":"ping"}')).toEqual({ type: 'ping' });
  });

  it('rejects unrelated/malformed messages without throwing', () => {
    for (const raw of [null, {}, '', 'invalid', 'null', '[]', '{"type":"pong"}',
      JSON.stringify({ ...selection(), doc_id: '' }),
      JSON.stringify({ ...selection(), item_ids: [1] }),
      JSON.stringify({ ...selection(), item_ids: [''] }),
      JSON.stringify({ ...selection(), labels: [] }),
      JSON.stringify({ ...selection(), labels: { 'window-001': 7 } }),
    ]) expect(decodeLiveMessage(raw)).toBeNull();
  });

  it('deduplicates IDs and limits labels to selected IDs', () => {
    expect(decodeLiveMessage(JSON.stringify(selection(['window-001', 'window-001'], {
      'window-001': '9', other: '10',
    })))).toEqual(selection(['window-001'], { 'window-001': '9' }));
  });

  it('compares effective labels rather than JSON property order or omitted defaults', () => {
    expect(sameHighlight(selection(), selection(undefined, { 'window-002': '2', 'window-001': '1' }))).toBe(true);
    expect(sameHighlight(selection(), selection(['window-002', 'window-001'], {
      'window-001': '1', 'window-002': '2',
    }))).toBe(true);
    expect(sameHighlight(selection(), selection(['window-002', 'window-001']))).toBe(false);
    expect(sameHighlight(selection(), { ...selection(), doc_id: 'other' })).toBe(false);
    expect(sameHighlight(selection(), selection(undefined, { 'window-001': '7' }))).toBe(false);
  });
});

describe('shared WebSocket lifecycle and echo suppression', () => {
  it('uses one connection for subscribers, answers ping, and ignores its broadcast echo', () => {
    const { client, connect, sockets } = transport();
    const a = vi.fn();
    const b = vi.fn();
    const stopA = client.onHighlight(a);
    const stopB = client.onHighlight(b);
    expect(connect).toHaveBeenCalledOnce();
    sockets[0].open();
    sockets[0].receive({ type: 'ping' });
    expect(sockets[0].sent).toEqual(['{"type":"pong"}']);
    const event = selection();
    client.sendHighlight(event.doc_id, event.item_ids);
    expect(a).toHaveBeenCalledOnce();
    expect(b).toHaveBeenCalledOnce();
    sockets[0].receive({ ...event, labels: { 'window-001': '1', 'window-002': '2' } });
    client.sendHighlight(event.doc_id, event.item_ids);
    expect(a).toHaveBeenCalledOnce();
    expect(sockets[0].sent).toHaveLength(2);
    stopA();
    expect(sockets[0].readyState).toBe(1);
    stopB();
    expect(sockets[0].readyState).toBe(3);
  });

  it('delivers changed remote labels and clear once without sending them back', () => {
    const { client, sockets } = transport();
    const callback = vi.fn();
    const stop = client.onHighlight(callback);
    sockets[0].open();
    sockets[0].receive(selection());
    sockets[0].receive(selection());
    sockets[0].receive(selection(undefined, { 'window-001': '7', 'window-002': '12' }));
    sockets[0].receive(selection([]));
    expect(callback).toHaveBeenCalledTimes(3);
    expect(callback.mock.calls[1][0].labels).toEqual({ 'window-001': '7', 'window-002': '12' });
    expect(sockets[0].sent).toEqual([]);
    stop();
  });

  it('backs off, queues only the latest selection per document, and resets after opening', () => {
    vi.useFakeTimers();
    const { client, sockets, connect } = transport();
    const stop = client.onHighlight(vi.fn());
    sockets[0].close();
    client.sendHighlight('generated-for-demo', ['window-001']);
    client.sendHighlight('generated-for-demo', []);
    client.sendHighlight('other-doc', ['wall-001'], { 'wall-001': '12' });
    vi.advanceTimersByTime(249);
    expect(connect).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(1);
    expect(connect).toHaveBeenCalledTimes(2);
    sockets[1].close();
    vi.advanceTimersByTime(499);
    expect(connect).toHaveBeenCalledTimes(2);
    vi.advanceTimersByTime(1);
    sockets[2].open();
    expect(sockets[2].sent.map((raw) => JSON.parse(raw))).toEqual([
      selection([]), { type: 'scene.highlight', doc_id: 'other-doc', item_ids: ['wall-001'], labels: { 'wall-001': '12' } },
    ]);
    sockets[2].close();
    vi.advanceTimersByTime(250);
    expect(connect).toHaveBeenCalledTimes(4);
    stop();
    vi.runAllTimers();
    expect(connect).toHaveBeenCalledTimes(4);
  });

  it('retries constructor failures and cancels the retry when unmounted', () => {
    vi.useFakeTimers();
    const connect = vi.fn(() => { throw new Error('offline'); });
    const client = createLiveHighlightClient({ url: 'wss://demo/ws', connect });
    const stop = client.onHighlight(vi.fn());
    vi.advanceTimersByTime(250);
    expect(connect).toHaveBeenCalledTimes(2);
    stop();
    vi.runAllTimers();
    expect(connect).toHaveBeenCalledTimes(2);
  });
});

function viewerStub(loaded = true) {
  let state: HighlightState = { highlighted: [], dimmed: 0, labels: {} };
  const listeners = new Set<(state: HighlightState) => void>();
  const viewer = {
    scene: (loaded ? { manifest: { doc_id: 'generated-for-demo' } } : null) as Viewer['scene'],
    highlight: vi.fn((ids: readonly string[], options?: HighlightOptions) => {
      state = { highlighted: [...ids], dimmed: 0, labels: Object.fromEntries(ids.map((id, i) => [id, options?.labels?.[id] ?? String(i + 1)])) };
      listeners.forEach((callback) => callback(state));
    }),
    getHighlightState: () => state,
    onHighlightChange(callback: (state: HighlightState) => void) {
      listeners.add(callback);
      return () => { listeners.delete(callback); };
    },
  };
  return viewer;
}

function channelStub() {
  const listeners = new Set<(event: HighlightMessage) => void>();
  const channel: HighlightChannel = {
    onHighlight(callback) { listeners.add(callback); return () => { listeners.delete(callback); }; },
    sendHighlight: vi.fn(),
  };
  return { channel, receive: (event: HighlightMessage) => listeners.forEach((cb) => cb(event)) };
}

describe('viewer live binding', () => {
  it('scopes by document, preserves labels, suppresses echoes, and publishes local clear', () => {
    const viewer = viewerStub();
    const { channel, receive } = channelStub();
    const live = bindLiveHighlight(viewer, undefined, channel);
    receive({ ...selection(), doc_id: 'another-doc' });
    expect(viewer.highlight).not.toHaveBeenCalled();
    const event = selection(undefined, { 'window-001': '7', 'window-002': '12' });
    receive(event);
    expect(viewer.getHighlightState().labels).toEqual(event.labels);
    expect(channel.sendHighlight).not.toHaveBeenCalled();
    receive(event);
    expect(viewer.highlight).toHaveBeenCalledOnce();
    viewer.highlight(['wall-001'], { labels: { 'wall-001': '9' } });
    expect(channel.sendHighlight).toHaveBeenLastCalledWith('generated-for-demo', ['wall-001'], { 'wall-001': '9' });
    viewer.highlight([]);
    expect(channel.sendHighlight).toHaveBeenLastCalledWith('generated-for-demo', [], {});
    live.dispose();
    receive(event);
    viewer.highlight(['window-001']);
    expect(channel.sendHighlight).toHaveBeenCalledTimes(2);
  });

  it('retains the latest matching update while geometry loads', () => {
    const viewer = viewerStub(false);
    const { channel, receive } = channelStub();
    const live = bindLiveHighlight(viewer, 'generated-for-demo', channel);
    receive(selection(['window-001']));
    receive(selection(['window-002'], { 'window-002': '12' }));
    receive({ ...selection(), doc_id: 'another-doc' });
    expect(viewer.highlight).not.toHaveBeenCalled();
    viewer.scene = { manifest: { doc_id: 'generated-for-demo' } } as Viewer['scene'];
    live.sceneReady();
    expect(viewer.getHighlightState().highlighted).toEqual(['window-002']);
    expect(viewer.getHighlightState().labels).toEqual({ 'window-002': '12' });
    expect(channel.sendHighlight).not.toHaveBeenCalled();
    live.dispose();
  });

  it('keeps two viewers in one tab in step without another server echo', () => {
    const { client, sockets } = transport();
    const a = viewerStub();
    const b = viewerStub();
    const liveA = bindLiveHighlight(a, undefined, client);
    const liveB = bindLiveHighlight(b, undefined, client);
    sockets[0].open();
    a.highlight(['window-001'], { labels: { 'window-001': '12' } });
    expect(b.getHighlightState()).toEqual(a.getHighlightState());
    expect(sockets[0].sent).toHaveLength(1);
    sockets[0].receive(JSON.parse(sockets[0].sent[0]));
    expect(a.highlight).toHaveBeenCalledOnce();
    expect(b.highlight).toHaveBeenCalledOnce();
    liveA.dispose();
    liveB.dispose();
  });
});
