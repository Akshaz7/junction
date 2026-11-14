import { describe, expect, it, vi } from 'vitest';
import { applyCommand, applyState, emptyCommandState, readCommandState, type SceneCommand, type SceneSnapshot } from '../commands';
import { createLiveHighlightClient, decodeLiveMessage, type SceneEvent } from '../liveHighlight';
import { bindLiveCommands, bindLiveHighlight } from '../liveViewerHighlight';
import type { Viewer } from '../viewer';
import type { HighlightState } from '../highlight';

class Socket {
  readyState = 0;
  sent: string[] = [];
  listeners = new Map<string, ((event: { data?: string }) => void)[]>();
  addEventListener(type: string, fn: (event: { data?: string }) => void) {
    this.listeners.set(type, [...this.listeners.get(type) ?? [], fn]);
  }
  emit(type: string, event = {}) { for (const fn of this.listeners.get(type) ?? []) fn(event); }
  open() { this.readyState = 1; this.emit('open'); }
  send(raw: string) { this.sent.push(raw); }
  receive(event: object) { this.emit('message', { data: JSON.stringify(event) }); }
  close() { this.readyState = 3; this.emit('close'); }
}

function transport() {
  const socket = new Socket();
  const connect = vi.fn(() => socket as unknown as WebSocket);
  const channel = createLiveHighlightClient({ url: 'ws://demo/ws', connect });
  return { socket, channel, connect };
}

function viewerStub(loaded = true) {
  let state = emptyCommandState();
  let applying = false;
  const commands = new Set<(cmd: SceneCommand) => void>();
  const highlights = new Set<(state: HighlightState) => void>();
  const highlightState = (): HighlightState => ({ highlighted: [...state.highlighted.keys()], dimmed: 0, labels: Object.fromEntries(state.highlighted) });
  const viewer = {
    scene: (loaded ? { manifest: { doc_id: 'demo' } } : null) as Viewer['scene'],
    applyCommand: vi.fn((cmd: SceneCommand) => {
      state = applyCommand(state, cmd);
      applying = true; for (const callback of highlights) callback(highlightState()); applying = false;
      for (const callback of commands) callback(cmd);
    }),
    applyState: vi.fn((snapshot: SceneSnapshot) => { state = applyState(snapshot); }),
    getCommandState: () => readCommandState(state),
    onCommandChange(callback: (cmd: SceneCommand) => void) { commands.add(callback); return () => { commands.delete(callback); }; },
    highlight: vi.fn(), getHighlightState: highlightState, isApplyingCommand: () => applying,
    onHighlightChange(callback: (state: HighlightState) => void) { highlights.add(callback); return () => { highlights.delete(callback); }; },
  };
  return viewer;
}

const edit = (op: SceneCommand['op'], item_ids: string[], edit_id: string): SceneEvent => ({ type: 'scene.edit', doc_id: 'demo', op, item_ids, edit_id });

describe('scene commands over the shared highlight WebSocket', () => {
  it('validates scene.edit and scene.state; ignores malformed events', () => {
    const event = edit('hide', ['W3'], 'edit1');
    expect(decodeLiveMessage(JSON.stringify(event))).toEqual(event);
    const snapshot = { type: 'scene.state', doc_id: 'demo', hidden: ['a'], highlighted: ['b'], labels: { b: 'W2' } };
    expect(decodeLiveMessage(JSON.stringify(snapshot))).toEqual(snapshot);
    for (const invalid of [
      { ...event, op: 'delete' }, { ...event, item_ids: [7] }, { ...event, labels: { a: 5 } },
      { ...snapshot, hidden: 'a' }, { ...snapshot, labels: [] }, { ...snapshot, isolated: [null] },
    ]) expect(decodeLiveMessage(JSON.stringify(invalid))).toBeNull();
  });

  it('preserves hide/restore order while offline and suppresses duplicate server echoes', () => {
    const { socket, channel } = transport();
    const callback = vi.fn(); const stop = channel.onSceneEvent(callback);
    channel.sendCommand('demo', { op: 'hide', item_ids: ['a'] });
    channel.sendCommand('demo', { op: 'restore', item_ids: ['a'] });
    expect(callback).toHaveBeenCalledTimes(2); expect(socket.sent).toHaveLength(0);
    socket.open();
    expect(socket.sent.map((raw) => JSON.parse(raw).op)).toEqual(['hide', 'restore']);
    for (const raw of socket.sent) socket.receive(JSON.parse(raw));
    expect(callback).toHaveBeenCalledTimes(2);
    const late = vi.fn(); const stopLate = channel.onSceneEvent(late);
    expect(late).toHaveBeenCalledWith(expect.objectContaining({ type: 'scene.state', hidden: [] }));
    stop(); stopLate(); expect(socket.readyState).toBe(3);
  });

  it('retains omitted versus explicit labels when replaying a snapshot to a late viewer', () => {
    const { socket, channel } = transport();
    const stop = channel.onSceneEvent(vi.fn()); socket.open();
    socket.receive({ ...edit('highlight', ['a', 'b'], 'tags'), labels: { a: 'a' } });
    const late = vi.fn(); const stopLate = channel.onSceneEvent(late);
    expect(late).toHaveBeenCalledWith(expect.objectContaining({ highlighted: ['a', 'b'], labels: { a: 'a' } }));
    stopLate(); stop();
  });

  it('buffers all loading edits in order, scopes documents, and replaces the layer from a snapshot', () => {
    const { socket, channel } = transport(); const viewer = viewerStub(false);
    const live = bindLiveCommands(viewer, 'demo', channel); socket.open();
    socket.receive(edit('highlight', ['a', 'b'], '1'));
    socket.receive(edit('hide', ['a'], '2'));
    socket.receive(edit('restore', ['a'], '3'));
    socket.receive({ ...edit('hide', ['b'], '4'), doc_id: 'elsewhere' });
    expect(viewer.applyCommand).not.toHaveBeenCalled();
    viewer.scene = { manifest: { doc_id: 'demo' } } as Viewer['scene']; live.sceneReady();
    expect(viewer.applyCommand).toHaveBeenCalledTimes(3);
    expect(viewer.getCommandState()).toEqual({ hidden: [], highlighted: { b: 'b' }, isolated: null });
    socket.receive({ type: 'scene.state', doc_id: 'demo', hidden: ['b'], highlighted: ['a'], labels: { a: 'W1' }, isolated: ['a'] });
    expect(viewer.getCommandState()).toEqual({ hidden: ['b'], highlighted: { a: 'W1' }, isolated: ['a'] });
    expect(socket.sent).toHaveLength(0);
    live.dispose(); socket.receive(edit('reset', [], '5'));
    expect(viewer.getCommandState().hidden).toEqual(['b']);
  });

  it('two viewers share one socket, apply local commands once and never publish command highlights as legacy echoes', () => {
    const { socket, channel, connect } = transport(); const a = viewerStub(); const b = viewerStub();
    const ha = bindLiveHighlight(a, 'demo', channel); const hb = bindLiveHighlight(b, 'demo', channel);
    const ca = bindLiveCommands(a, 'demo', channel); const cb = bindLiveCommands(b, 'demo', channel);
    socket.open(); expect(connect).toHaveBeenCalledOnce();
    a.applyCommand({ op: 'highlight', item_ids: ['a', 'b'], labels: { a: 'W1', b: 'W2' } });
    a.applyCommand({ op: 'hide', item_ids: ['a'] });
    expect(a.applyCommand).toHaveBeenCalledTimes(2); expect(b.applyCommand).toHaveBeenCalledTimes(2);
    expect(a.getCommandState()).toEqual(b.getCommandState());
    expect(socket.sent.map((raw) => JSON.parse(raw).type)).toEqual(['scene.edit', 'scene.edit']);
    for (const raw of socket.sent) socket.receive(JSON.parse(raw));
    expect(b.applyCommand).toHaveBeenCalledTimes(2);
    ha.dispose(); hb.dispose(); expect(socket.readyState).toBe(1);
    ca.dispose(); cb.dispose(); expect(socket.readyState).toBe(3);
  });
});
