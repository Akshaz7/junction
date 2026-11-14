// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { DocumentViewer } from '../../components/document-viewer';
import { workspaceApi } from '../../lib/api';
import { demoDocument, makeDemoAnswer } from '../../mock/handler';
import { applyCommand, emptyCommandState } from '../commands';
import { getLinkedItem, setHover, setSelected } from '../link';
import type { SceneEvent } from '../liveHighlight';

const transport = vi.hoisted(() => ({
  listeners: new Set<(event: SceneEvent) => void>(),
  sendCommand: vi.fn(),
  options: vi.fn(),
}));
vi.mock('../liveHighlight', async (original) => ({
  ...await original<typeof import('../liveHighlight')>(),
  createLiveHighlightClient: (options: unknown) => {
    transport.options(options);
    return { sendCommand: transport.sendCommand, onSceneEvent(callback: (event: SceneEvent) => void) {
      transport.listeners.add(callback); return () => transport.listeners.delete(callback);
    } };
  },
}));
vi.mock('../../components/viewer-tools/room-labels', () => ({ RoomLabels: () => null }));

let host: HTMLDivElement, root: Root;
const answer = () => makeDemoAnswer('How many windows are there?');
let current = answer();
async function render(chatId = 'unseen-chat') {
  await act(async () => root.render(<DocumentViewer answer={current} citation={current.citations[0]}
    sheet={false} onClose={() => {}} chatId={chatId} />));
}
async function loadedImage() {
  const image = host.querySelector('img')!;
  Object.defineProperties(image, { naturalWidth: { value: 1000 }, naturalHeight: { value: 800 } });
  await act(async () => image.dispatchEvent(new Event('load')));
}
async function event(value: SceneEvent) {
  await act(async () => { for (const callback of transport.listeners) callback(value); });
}
const boxes = () => host.querySelectorAll('[data-testid^="evidence-box-"]');
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} });
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => { cb(0); return 0; });
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({})));
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:drawing') });
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
  vi.spyOn(workspaceApi, 'getDocument').mockResolvedValue(demoDocument);
  vi.spyOn(workspaceApi, 'getPageImage').mockResolvedValue(new Blob());
  vi.spyOn(workspaceApi, 'getDocumentTags').mockResolvedValue({});
  transport.sendCommand.mockReset(); transport.options.mockClear(); current = answer();
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount()); host.remove();
  expect(transport.listeners.size).toBe(0);
  vi.restoreAllMocks(); vi.unstubAllGlobals();
});

it('the 2D toolbar clears evidence and linked selection through a chat-scoped highlight command', async () => {
  await render(); await loadedImage(); expect(boxes().length).toBeGreaterThan(0);
  await act(async () => { setHover('window-001', '3d'); setSelected('window-001', '3d'); });
  const button = [...host.querySelectorAll('button')].find((node) => node.textContent === 'Clear highlights')!;
  await act(async () => button.click());
  expect(boxes().length).toBe(0);
  expect(transport.options).toHaveBeenCalledWith({ chat_id: 'unseen-chat' });
  const command = { op: 'highlight', item_ids: [] } as const;
  expect(transport.sendCommand).toHaveBeenCalledExactlyOnceWith(current.doc_ids[0], command);
  let state = applyCommand(emptyCommandState(), { op: 'hide', item_ids: ['removed'] });
  state = applyCommand(state, { op: 'isolate', item_ids: ['kept'] });
  state = applyCommand(state, { ...command, item_ids: [] });
  expect([...state.hidden]).toEqual(['removed']); expect([...state.isolated!]).toEqual(['kept']);
  expect(getLinkedItem()).toMatchObject({ hovered: null, selected: null });
  current = { ...answer(), answer_id: 'next-answer' };
  await render(); expect(boxes().length).toBeGreaterThan(0);
});

it('honours a reloaded clear snapshot, ignores other documents, and accepts a later highlight', async () => {
  await render(); await loadedImage();
  await event({ type: 'scene.state', doc_id: current.doc_ids[0], hidden: ['removed'], highlighted: [], labels: {}, isolated: null });
  expect(boxes().length).toBe(0);
  await event({ type: 'scene.edit', doc_id: 'another-drawing', op: 'highlight', item_ids: ['other'] });
  expect(boxes().length).toBe(0);
  await event({ type: 'scene.edit', doc_id: current.doc_ids[0], op: 'highlight', item_ids: ['window-001'] });
  expect(boxes().length).toBeGreaterThan(0);
});
