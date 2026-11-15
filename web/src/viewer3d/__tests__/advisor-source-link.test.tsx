import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { sourcedCards } from '../advisor';
import { AdvisorCardView, sourceLabel } from '../AdvisorCardView';

const quote = 'Each storey shall have at least two separate and appropriately located exits that are at least 1200 mm wide, unless the storey is small enough that one exit is safe.';
const card = (source: Record<string, unknown>) => ({
  card_id: 'c1', kind: 'warning', severity: 'violation', title: 'No entrance door left on the drawing', body: 'b', item_ids: ['a'],
  source: { type: 'rule', ref: 'fi-fire-exits-per-storey', title: 'Decree of the Ministry of the Environment on the fire safety of buildings 848/2017, 33 §', quote, ...source },
});

describe('advisor card source link', () => {
  it('keeps http(s) url and section, drops other urls, still accepts cards without them', () => {
    const [withUrl] = sourcedCards({ cards: [card({ url: 'https://www.finlex.fi/fi/laki/alkup/2017/20170848', section: '§33' })] });
    expect(withUrl.source.url).toBe('https://www.finlex.fi/fi/laki/alkup/2017/20170848');
    expect(withUrl.source.section).toBe('§33');
    const [bad] = sourcedCards({ cards: [card({ url: 'javascript:alert(1)', section: '  ' })] });
    expect(bad.source.url).toBeUndefined();
    expect(bad.source.section).toBeUndefined();
    const [plain] = sourcedCards({ cards: [card({})] });
    expect(plain.source).not.toHaveProperty('url');
  });

  it('renders the full quote and a new-tab link only for http(s) urls', () => {
    const [withUrl] = sourcedCards({ cards: [card({ url: 'https://www.finlex.fi/x' })] });
    const html = renderToStaticMarkup(createElement(AdvisorCardView, { card: withUrl }));
    expect(html).toContain(quote);
    expect(html).toContain('href="https://www.finlex.fi/x"');
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noreferrer"');
    expect(html).toContain('Finlex: legal text (Finnish)');
    const [plain] = sourcedCards({ cards: [card({})] });
    expect(renderToStaticMarkup(createElement(AdvisorCardView, { card: plain }))).not.toContain('<a ');
  });

  it('adds the section to the label when the title has none', () => {
    expect(sourceLabel({ type: 'rule', ref: 'r', title: 'Decree 848/2017', quote: 'q', section: '33' })).toBe('Decree 848/2017 §33');
    expect(sourceLabel({ type: 'rule', ref: 'r', title: 'Decree 848/2017, 34 §', quote: 'q', section: '§33' })).toBe('Decree 848/2017 §34');
  });
});
