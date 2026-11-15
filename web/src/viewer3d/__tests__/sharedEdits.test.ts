import { describe, expect, it, vi } from 'vitest';
import { BoxGeometry, Group, Mesh, MeshStandardMaterial } from 'three';
import { createScene, disposeScene, type SceneManifest } from '../scene';
import { createEditLayer } from '../edits';
import { applyCommand, applyState, emptyCommandState, readCommandState, type SceneCommand, type SceneSnapshot } from '../commands';
import { createLiveHighlightClient, decodeLiveMessage } from '../liveHighlight';
import { bindLiveCommands } from '../liveViewerHighlight';
import { emptyChatEdits, reduceSceneEvent } from '../../lib/scene-edits';
import { drawingSnapshot, syncSceneSnapshot } from '../../lib/scene-snapshot';
import type { Viewer } from '../viewer';

/** Chat and Edit panel share one hidden layer: either side can undo the other. */
function fixture() {
  const root = new Group();
  const surface = new MeshStandardMaterial({ color: '#222222' });
  const ids = ['wall', 'door', 'door2'];
  for (const id of ids) { const m = new Mesh(new BoxGeometry(1, 2, 0.2), surface); m.name = id; root.add(m); }
  const manifest: SceneManifest = { doc_id: 'generated-for-demo', glb: 'scene.glb', usdz: null, units: 'm', up: 'Y', origin_offset_m: [0, 0, 0], storeys: [],
    items: Object.fromEntries(ids.map((id) => [id, { node: id, kind: id === 'wall' ? 'wall' : 'door', bbox_m: null, storey: null, usd_name: id }])) };
  const scene = createScene(manifest, { scene: root, parser: { associations: new Map(), json: {} } } as Parameters<typeof createScene>[1]);
  let commands = emptyCommandState();
  const sent: SceneCommand[] = [];
  const layer = createEditLayer(scene, { apply: (cmd) => { sent.push(cmd); commands = applyCommand(commands, cmd); }, hidden: () => [...commands.hidden] });
  /** What the viewer does for a remote (chat) command: apply it, then note new hides. */
  const remote = (cmd: SceneCommand) => {
    const before = commands.hidden; commands = applyCommand(commands, cmd);
    layer.noteExternalHide([...commands.hidden].filter((id) => !before.has(id)));
  };
  return { layer, scene, sent, remote, surface, hidden: () => [...commands.hidden] };
}

describe('shared edit layer (chat + Edit panel)', () => {
  it('a chat removal joins Undo: one click brings the whole chat group back', () => {
    const { layer, scene, remote, hidden, sent } = fixture();
    remote({ op: 'hide', item_ids: ['door', 'door2'] });
    expect(layer.state().undoCount).toBe(1);
    expect(layer.undo()).toEqual({ op: 'restore', item_ids: ['door', 'door2'], detail: { undo: 'hide', external: true } });
    expect(hidden()).toEqual([]);
    expect(sent.at(-1)).toEqual({ op: 'restore', item_ids: ['door', 'door2'] });
    expect(layer.state().undoCount).toBe(0);
    layer.dispose(); disposeScene(scene);
  });

  it('a manual removal the chat already restored is skipped by Undo, not replayed', () => {
    const { layer, scene, remote, hidden } = fixture();
    layer.move('wall', scene.items.get('wall')!.position.clone(), 0.5, 0, true);
    layer.remove('door');
    remote({ op: 'restore', item_ids: ['door'] });       // chat: "put the door back"
    expect(hidden()).toEqual([]);
    expect(layer.state().undoCount).toBe(1);               // only the move is left
    expect(layer.undo()?.op).toBe('move');
    expect(layer.undo()).toBeNull();
    layer.dispose(); disposeScene(scene);
  });

  it('restores a chat-hidden item by hand, Undo hides it again, Reset brings everything back', () => {
    const { layer, scene, remote, hidden, sent } = fixture();
    remote({ op: 'hide', item_ids: ['door'] });
    remote({ op: 'hide', item_ids: ['door2'] });
    expect(layer.restore(['door', 'wall'])).toEqual({ op: 'restore', item_ids: ['door'], detail: {} });
    expect(hidden()).toEqual(['door2']);
    expect(layer.undo()).toEqual({ op: 'hide', item_ids: ['door'], detail: { undo: 'restore' } });
    expect(hidden()).toEqual(['door2', 'door']);
    const reset = layer.reset();
    expect(reset?.op).toBe('reset');
    expect(new Set(reset?.item_ids)).toEqual(new Set(['door', 'door2']));
    expect(hidden()).toEqual([]);
    expect(sent.at(-1)).toEqual({ op: 'restore', item_ids: ['door2', 'door'] });
    expect(layer.state().undoCount).toBe(0);
    expect(layer.reset()).toBeNull();
    layer.dispose(); disposeScene(scene);
  });
});

describe('shared moves and materials', () => {
  it('a chat "put it back" (offset 0) reverts a manual move; Undo then undoes that revert', () => {
    const { layer, scene } = fixture();
    const wall = scene.items.get('wall')!;
    layer.move('wall', wall.position.clone(), 0.5, 0, true);
    expect(layer.state().moveDelta).toEqual({ wall: [0.5, 0] });
    layer.applyShared({ moved: {} });                     // chat: back where it was
    expect(wall.position.length()).toBe(0);
    expect(layer.state().moveDelta).toEqual({});
    expect(layer.state().undoCount).toBe(1);               // the manual move entry is stale; only the chat revert is left
    expect(layer.undo()?.detail).toMatchObject({ external: true });
    expect(layer.state().moveDelta).toEqual({ wall: [0.5, 0] });
    layer.dispose(); disposeScene(scene);
  });

  it('a shared move/material (chat, another client or saved chat state) joins Undo and Reset', () => {
    const { layer, scene, surface } = fixture();
    const wall = scene.items.get('wall')! as Mesh;
    layer.applyShared({ moved: { wall: [0, 1.5] }, materials: { wall: 'Glass', door: 'Bogus' } });
    expect(layer.state().moveDelta).toEqual({ wall: [0, 1.5] });
    expect(layer.state().materials).toEqual({ wall: 'Glass' });
    expect(layer.state().undoCount).toBe(2);
    layer.undo();                                          // newest first: the material
    expect(layer.state().materials).toEqual({});
    expect(wall.material).toBe(surface);
    layer.applyShared({ materials: { wall: 'Concrete' } });
    expect(layer.reset()?.item_ids).toEqual(['wall']);
    expect(layer.state()).toEqual({ undoCount: 0, moved: {}, moveDelta: {}, materials: {} });
    expect(wall.position.length()).toBe(0);
    expect(wall.material).toBe(surface);
    layer.dispose(); disposeScene(scene);
  });

  it('two manual moves undo one step at a time; Reset goes straight back to the original', () => {
    const { layer, scene } = fixture();
    const wall = scene.items.get('wall')!;
    layer.move('wall', wall.position.clone(), 1, 0, true);
    layer.move('wall', wall.position.clone(), 1, 0, true);
    expect(layer.state().moveDelta).toEqual({ wall: [2, 0] });
    layer.undo();
    expect(layer.state().moveDelta).toEqual({ wall: [1, 0] });
    layer.move('wall', wall.position.clone(), 1, 0, true);
    layer.reset();
    expect(wall.position.length()).toBe(0);
    layer.dispose(); disposeScene(scene);
  });
});

describe('chat edit layer carries moves and materials', () => {
  it('folds move/material/reset, survives a snapshot, and the viewer resyncs only when they differ', () => {
    let edits = reduceSceneEvent(emptyChatEdits(), { type: 'scene.edit', doc_id: 'd', op: 'hide', item_ids: ['a'], edit_id: '1' });
    expect(edits.docs.d).not.toHaveProperty('moved');      // nothing moved yet: snapshots leave local moves alone
    expect(drawingSnapshot(edits.docs.d)).not.toHaveProperty('moved');
    edits = reduceSceneEvent(edits, { type: 'scene.edit', doc_id: 'd', op: 'move', item_ids: ['w'], offset_m: [0.5, 0], edit_id: '2' });
    edits = reduceSceneEvent(edits, { type: 'scene.edit', doc_id: 'd', op: 'material', item_ids: ['wl'], material: 'Glass', edit_id: '3' });
    expect(edits.docs.d.moved).toEqual({ w: [0.5, 0] });
    expect(edits.docs.d.materials).toEqual({ wl: 'Glass' });
    const viewer = { getCommandState: () => ({ hidden: ['a'], highlighted: {}, isolated: null }), applyState: vi.fn(),
      getEditState: () => ({ moveDelta: { w: [0.5, 0] }, materials: { wl: 'Glass' } }) };
    syncSceneSnapshot(viewer, drawingSnapshot(edits.docs.d));
    expect(viewer.applyState).not.toHaveBeenCalled();     // the echo of a local edit is a no-op
    edits = reduceSceneEvent(edits, { type: 'scene.edit', doc_id: 'd', op: 'move', item_ids: ['w'], offset_m: [0, 0], edit_id: '4' });
    expect(edits.docs.d.moved).toEqual({});
    syncSceneSnapshot(viewer, drawingSnapshot(edits.docs.d));
    expect(viewer.applyState).toHaveBeenCalledWith(expect.objectContaining({ moved: {} }));
    edits = reduceSceneEvent(edits, { type: 'scene.edit', doc_id: 'd', op: 'reset', item_ids: [], edit_id: '5' });
    expect(edits.docs.d.materials).toEqual({});
    edits = reduceSceneEvent(edits, { type: 'scene.state', doc_id: 'd', hidden: [], highlighted: [], labels: {}, moved: { w: [1, 1] } });
    expect(edits.docs.d.moved).toEqual({ w: [1, 1] });
  });

  it('decodes move/material edits and state fields; rejects bad offsets', () => {
    const move = { type: 'scene.edit', doc_id: 'd', op: 'move', item_ids: ['w'], offset_m: [0.5, -1], edit_id: 'm' };
    expect(decodeLiveMessage(JSON.stringify(move))).toEqual(move);
    expect(decodeLiveMessage(JSON.stringify({ ...move, offset_m: [1] }))).toBeNull();
    expect(decodeLiveMessage(JSON.stringify({ ...move, op: 'material', material: 5 }))).toBeNull();
    expect(decodeLiveMessage(JSON.stringify({ ...move, op: 'material', material: null }))).not.toBeNull();
    const state = { type: 'scene.state', doc_id: 'd', hidden: [], highlighted: [], labels: {}, moved: { w: [1, 0] }, materials: { wl: 'Glass' } };
    expect(decodeLiveMessage(JSON.stringify(state))).toEqual(state);
    expect(decodeLiveMessage(JSON.stringify({ ...state, moved: { w: ['x', 0] } }))).toBeNull();
  });
});

describe('bindLiveCommands with a chat', () => {
  function stub() {
    let state = emptyCommandState();
    const listeners = new Set<(cmd: SceneCommand) => void>();
    return {
      scene: { manifest: { doc_id: 'demo' } } as Viewer['scene'],
      applyCommand: vi.fn((cmd: SceneCommand) => { state = applyCommand(state, cmd); for (const fn of listeners) fn(cmd); }),
      applyState: vi.fn((snapshot: SceneSnapshot) => { state = applyState(snapshot); }),
      onCommandChange(fn: (cmd: SceneCommand) => void) { listeners.add(fn); return () => { listeners.delete(fn); }; },
      state: () => readCommandState(state),
    };
  }

  it('sends manual edits with the chat id and ignores another chat\'s edits', () => {
    const sent: string[] = [];
    const socket = { readyState: 0, listeners: new Map<string, ((e: { data?: string }) => void)[]>(),
      addEventListener(type: string, fn: (e: { data?: string }) => void) { this.listeners.set(type, [...this.listeners.get(type) ?? [], fn]); },
      send(raw: string) { sent.push(raw); }, close() { this.readyState = 3; },
      emit(type: string, e = {}) { for (const fn of this.listeners.get(type) ?? []) fn(e); } };
    const channel = createLiveHighlightClient({ url: 'ws://demo/ws', connect: () => socket as unknown as WebSocket });
    const viewer = stub();
    let chat: string | undefined = 'chat-a';
    const live = bindLiveCommands(viewer, 'demo', channel, () => chat);
    socket.readyState = 1; socket.emit('open');
    viewer.applyCommand({ op: 'hide', item_ids: ['door'] });
    expect(JSON.parse(sent[0])).toMatchObject({ type: 'scene.edit', doc_id: 'demo', op: 'hide', item_ids: ['door'], chat_id: 'chat-a' });
    const receive = (event: object) => socket.emit('message', { data: JSON.stringify(event) });
    receive({ type: 'scene.edit', doc_id: 'demo', chat_id: 'chat-b', op: 'hide', item_ids: ['wall'], edit_id: 'b1' });
    expect(viewer.state().hidden).toEqual(['door']);
    receive({ type: 'scene.edit', doc_id: 'demo', chat_id: 'chat-a', op: 'restore', item_ids: ['door'], edit_id: 'a1' });
    expect(viewer.state().hidden).toEqual([]);
    chat = undefined;
    viewer.applyCommand({ op: 'hide', item_ids: ['wall'] });
    expect(JSON.parse(sent[1])).not.toHaveProperty('chat_id');
    live.dispose();
  });
});
