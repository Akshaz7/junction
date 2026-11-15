import type { ItemEdit } from './edits';

export type AdvisorSeverity = 'violation' | 'suggestion' | 'info';
export function cardSeverity(card: Pick<AdvisorCard, 'kind' | 'severity'>): AdvisorSeverity {
  if (card.severity === 'violation' || card.severity === 'suggestion' || card.severity === 'info') return card.severity;
  return card.kind === 'warning' ? 'violation' : card.kind === 'option' ? 'suggestion' : 'info';
}

export interface AdvisorCard {
  card_id: string;
  kind: 'warning' | 'option' | 'info';
  title: string;
  body: string;
  item_ids: string[];
  /** How many elements the check covered; item_ids is capped, so this can be larger. */
  item_total?: number;
  /** violation (red), suggestion (amber), info (grey); older cards only have `kind`. */
  severity?: AdvisorSeverity;
  /** Rule ids the check ran against. */
  checked?: string[];
  source: { type: 'rule' | 'material_table' | 'document'; ref: string; title: string; quote: string;
    /** Official page for the rule (government / EU text), so a violation can be checked externally. */
    url?: string | null; finnish_url?: string | null;
    /** Optional section label, e.g. "33 §". */
    section?: string };
}
export interface AdvisorEvent {
  type: 'advisor.cards';
  doc_id: string;
  chat_id?: string | null;
  cards: AdvisorCard[];
  /** Set when a scene reset/restore cleared or re-derived the cards. Monotonic: older versions are stale. */
  scene_version?: number;
  cleared?: boolean;
}
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === 'string' && !!value.trim();

/** Both HTTP and live cards must carry a complete source before rendering. */
export function sourcedCards(value: unknown): AdvisorCard[] {
  if (!record(value) || !Array.isArray(value.cards)) return [];
  const cards: AdvisorCard[] = [];
  for (const entry of value.cards) {
    if (!record(entry) || !record(entry.source)) continue;
    const source = entry.source;
    if (!['rule', 'material_table', 'document'].includes(source.type as string)
      || !['ref', 'title', 'quote'].every((key) => text(source[key]))
      || !['warning', 'option', 'info'].includes(entry.kind as string)
      || !['card_id', 'title', 'body'].every((key) => text(entry[key]))
      || !Array.isArray(entry.item_ids) || !entry.item_ids.every(text)
      || cards.some((card) => card.card_id === entry.card_id)) continue;
    const severity = ['violation', 'suggestion', 'info'].includes(entry.severity as string) ? entry.severity : undefined;
    const checked = Array.isArray(entry.checked) ? entry.checked.filter(text) : undefined;
    const { url, section, ...base } = source;
    const cleanSource = {
      ...base,
      ...(typeof url === 'string' && /^https?:\/\//i.test(url) ? { url } : {}),
      ...(text(section) ? { section } : {}),
    } as AdvisorCard['source'];
    cards.push({ ...(entry as unknown as AdvisorCard), source: cleanSource, severity: severity as AdvisorSeverity | undefined, checked });
    if (cards.length === 3) break;
  }
  return cards;
}

export function decodeAdvisorEvent(value: unknown): AdvisorEvent | null {
  if (!record(value) || value.type !== 'advisor.cards' || !text(value.doc_id)
    || !Array.isArray(value.cards) || (value.chat_id != null && typeof value.chat_id !== 'string')) return null;
  const scene_version = typeof value.scene_version === 'number' ? value.scene_version : undefined;
  return { type: 'advisor.cards', doc_id: value.doc_id, chat_id: value.chat_id as string | null | undefined, cards: sourcedCards(value),
    ...(scene_version !== undefined ? { scene_version } : {}), ...(value.cleared === true ? { cleared: true } : {}) };
}

/** Queue every edit; debounce the network burst without losing intermediate operations. */
export function createAdvisorRequests(options: {
  doc_id: string;
  chat_id?: string;
  onLoading(): void;
  onCards(cards: AdvisorCard[]): void;
  onError(): void;
  request?: typeof fetch;
}) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let queue: ItemEdit[] = [];
  let revision = 0;
  let disposed = false;
  let sceneVersion = 0;
  let sending = Promise.resolve();
  const controllers = new Set<AbortController>();

  function flush() {
    const batch = queue; queue = [];
    const version = revision;
    // Keep batches in edit order even when an older HTTP call takes longer than
    // the debounce interval. A rejected operation must not drop later edits.
    sending = sending.then(async () => {
      if (disposed) return;
      const controller = new AbortController();
      controllers.add(controller);
      try {
        for (let index = 0; index < batch.length; index++) {
          if (disposed) return;
          try {
            const response = await (options.request ?? fetch)('/api/advise', {
              method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: controller.signal,
              body: JSON.stringify({ doc_id: options.doc_id, ...(options.chat_id ? { chat_id: options.chat_id } : {}), edit: batch[index] }),
            });
            if (!response.ok) throw new Error('Advisor unavailable');
            const data: unknown = await response.json();
            if (!disposed && version === revision && index === batch.length - 1) options.onCards(sourcedCards(data));
          } catch {
            if (!disposed && version === revision && index === batch.length - 1) options.onError();
          }
        }
      } finally { controllers.delete(controller); }
    });
  }
  return {
    enqueue(edit: ItemEdit) {
      if (disposed) return;
      queue.push(edit); revision++;
      options.onLoading();
      clearTimeout(timer); timer = setTimeout(() => { void flush(); }, 400);
    },
    receive(event: AdvisorEvent) {
      if (disposed || event.doc_id !== options.doc_id || (event.chat_id ?? null) !== (options.chat_id ?? null)) return;
      if (event.scene_version !== undefined) {
        if (event.scene_version < sceneVersion) return;  // a card event from before the latest reset
        sceneVersion = event.scene_version;
        queue = []; clearTimeout(timer);  // queued checks were for the old scene
      }
      revision++;  // also discards any in-flight HTTP result for the old scene
      options.onCards(event.cards);
    },
    dispose() {
      disposed = true; clearTimeout(timer); queue = [];
      for (const controller of controllers) controller.abort();
      controllers.clear();
    },
  };
}
