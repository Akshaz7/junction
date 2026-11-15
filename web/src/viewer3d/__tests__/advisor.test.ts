import { afterEach, describe, expect, it, vi } from 'vitest';
import { createAdvisorRequests, sourcedCards, type AdvisorCard } from '../advisor';
import { createLiveHighlightClient, decodeLiveMessage } from '../liveHighlight';

const card: AdvisorCard = { card_id: 'advisor-fixture', kind: 'info', title: 'Generated for demo', body: 'Generated for demo.', item_ids: ['door'],
  source: { type: 'document', ref: 'advisor-fixture', title: 'Generated for demo', quote: 'This text is generated for demo.' } };
const event = { type: 'advisor.cards' as const, doc_id: 'demo', chat_id: 'chat', cards: [card] };
afterEach(() => vi.useRealTimers());

describe('sourced advisor cards and edit requests', () => {
  it('drops missing/malformed sources, deduplicates cards and caps both transports at three', () => {
    const raw = { ...event, cards: [
      { ...card, source: undefined }, { ...card, source: { ...card.source, quote: '' } }, card, card,
      ...[2, 3, 4].map((id) => ({ ...card, card_id: String(id) })),
    ] };
    expect(sourcedCards(raw).map((entry) => entry.card_id)).toEqual(['advisor-fixture', '2', '3']);
    expect(decodeLiveMessage(JSON.stringify(raw))).toEqual({ ...event, cards: sourcedCards(raw) });
  });

  it('debounces for 400 ms, sends each operation and ignores POST results superseded by a live update', async () => {
    vi.useFakeTimers();
    let finish: (response: Response) => void = () => {};
    const request = vi.fn<typeof fetch>().mockResolvedValueOnce(new Response(JSON.stringify({ cards: [] })))
      .mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const onCards = vi.fn(); const onError = vi.fn();
    const client = createAdvisorRequests({ doc_id: 'demo', chat_id: 'chat', request, onLoading: vi.fn(), onCards, onError });
    client.enqueue({ op: 'hide', item_ids: ['door'], detail: {} });
    await vi.advanceTimersByTimeAsync(200);
    client.enqueue({ op: 'material', item_ids: ['wall'], detail: { material: 'Concrete' } });
    await vi.advanceTimersByTimeAsync(399); expect(request).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1); expect(request).toHaveBeenCalledTimes(2);
    const payloads = request.mock.calls.map(([, options]) => JSON.parse(options!.body as string));
    expect(payloads[0]).toEqual({ doc_id: 'demo', chat_id: 'chat', edit: { op: 'hide', item_ids: ['door'], detail: {} } });
    expect(payloads[1].edit.detail).toEqual({ material: 'Concrete' });
    client.receive({ ...event, doc_id: 'other' });
    client.receive({ ...event, chat_id: 'other' });
    expect(onCards).not.toHaveBeenCalled();
    client.receive(event); expect(onCards).toHaveBeenLastCalledWith([card]);
    finish(new Response(JSON.stringify({ cards: [] })));
    await vi.advanceTimersByTimeAsync(1);
    expect(onCards).toHaveBeenCalledOnce(); expect(onError).not.toHaveBeenCalled();
    client.dispose();
  });

  it('clears the previous cards as soon as an undo/reset is queued and shows the recomputed (empty) set', async () => {
    vi.useFakeTimers();
    const request = vi.fn<typeof fetch>().mockResolvedValueOnce(new Response(JSON.stringify({ cards: [card] })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ cards: [] })));
    const seen: string[] = [];
    const client = createAdvisorRequests({ doc_id: 'demo', request, onError: vi.fn(),
      onLoading: () => seen.push('loading'), onCards: (cards) => seen.push(`cards:${cards.length}`) });
    client.enqueue({ op: 'hide', item_ids: ['door'], detail: {} });
    await vi.advanceTimersByTimeAsync(400);
    client.enqueue({ op: 'restore', item_ids: ['door'], detail: { undo: 'hide' } });
    expect(seen).toEqual(['loading', 'cards:1', 'loading']);
    await vi.advanceTimersByTimeAsync(400);
    expect(seen).toEqual(['loading', 'cards:1', 'loading', 'cards:0']);
    expect(JSON.parse(request.mock.calls[1][1]!.body as string).edit.op).toBe('restore');
    client.dispose();
  });

  it('cancels debounced work on scene disposal and reports failed advice without inventing an empty answer', async () => {
    vi.useFakeTimers();
    const request = vi.fn<typeof fetch>().mockResolvedValue(new Response('', { status: 422 }));
    const onCards = vi.fn(); const onError = vi.fn();
    const client = createAdvisorRequests({ doc_id: 'demo', request, onLoading: vi.fn(), onCards, onError });
    client.enqueue({ op: 'move', item_ids: ['wall'], detail: {} });
    await vi.advanceTimersByTimeAsync(400);
    expect(onError).toHaveBeenCalledOnce(); expect(onCards).not.toHaveBeenCalled();
    client.enqueue({ op: 'reset', item_ids: [], detail: {} }); client.dispose();
    await vi.advanceTimersByTimeAsync(500); expect(request).toHaveBeenCalledOnce();
  });

  it('sends later edits after a rejected operation and keeps later debounce batches in order', async () => {
    vi.useFakeTimers();
    let finish: (response: Response) => void = () => {};
    const request = vi.fn<typeof fetch>()
      .mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ cards: [] })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ cards: [card] })));
    const onCards = vi.fn();
    const client = createAdvisorRequests({ doc_id: 'demo', request, onLoading: vi.fn(), onCards, onError: vi.fn() });
    client.enqueue({ op: 'move', item_ids: ['door'], detail: {} });
    client.enqueue({ op: 'material', item_ids: ['wall'], detail: {} });
    await vi.advanceTimersByTimeAsync(400);
    client.enqueue({ op: 'reset', item_ids: [], detail: {} });
    await vi.advanceTimersByTimeAsync(400);
    expect(request).toHaveBeenCalledOnce();
    finish(new Response('', { status: 422 }));
    await vi.advanceTimersByTimeAsync(1);
    expect(request.mock.calls.map(([, options]) => JSON.parse(options!.body as string).edit.op)).toEqual(['move', 'material', 'reset']);
    expect(onCards).toHaveBeenCalledExactlyOnceWith([card]);
    client.dispose();
  });

  it('delivers advisor cards on the existing shared socket and keeps it open while subscribed', () => {
    const socket = new EventTarget() as EventTarget & { readyState: number; close: () => void };
    socket.readyState = 1; socket.close = vi.fn();
    const connect = vi.fn(() => socket as unknown as WebSocket);
    const client = createLiveHighlightClient({ url: 'ws://demo/ws', connect });
    const stopHighlight = client.onHighlight(vi.fn());
    const onCards = vi.fn(); const stopCards = client.onAdvisorCards(onCards);
    socket.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(event) }));
    expect(onCards).toHaveBeenCalledWith(event); expect(connect).toHaveBeenCalledOnce();
    stopHighlight(); expect(socket.close).not.toHaveBeenCalled();
    stopCards(); expect(socket.close).toHaveBeenCalledOnce();
  });

  it('drops stale cards on a remote reset: clear, ignore older versions, accept the re-derived cards', () => {
    const onCards = vi.fn();
    const client = createAdvisorRequests({ doc_id: 'demo', chat_id: 'chat', request: vi.fn<typeof fetch>(), onLoading: vi.fn(), onCards, onError: vi.fn() });
    client.receive({ ...event, cards: [], cleared: true, scene_version: 20 });
    expect(onCards).toHaveBeenLastCalledWith([]);
    client.receive({ ...event, scene_version: 10 });  // derived before the reset, arrives late
    expect(onCards).toHaveBeenCalledOnce();
    client.receive({ ...event, scene_version: 30 });
    expect(onCards).toHaveBeenLastCalledWith([card]);
    client.dispose();
  });

  it('decodes scene_version and cleared from the wire', () => {
    const raw = { ...event, cards: [], cleared: true, scene_version: 5 };
    expect(decodeLiveMessage(JSON.stringify(raw))).toEqual({ ...event, cards: [], cleared: true, scene_version: 5 });
  });
});
