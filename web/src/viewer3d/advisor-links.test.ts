import { describe, expect, it } from 'vitest'
import { sourceLinkLabel, sourceLinks } from './AdvisorCardView'

describe('advisor card source links', () => {
  const base = { type: 'rule' as const, ref: 'fi-fire-exits-per-storey', title: '848/2017, 33 §', quote: 'q' }

  it('lists the English text first, then the Finnish legal text, http(s) only, no duplicates', () => {
    expect(sourceLinks({ ...base, url: 'https://technical-regulation-information-system.ec.europa.eu/en/notification/18529/text/F/EN',
      finnish_url: 'https://www.finlex.fi/fi/lainsaadanto/saadoskokoelma/2017/848' })).toEqual([
      'https://technical-regulation-information-system.ec.europa.eu/en/notification/18529/text/F/EN',
      'https://www.finlex.fi/fi/lainsaadanto/saadoskokoelma/2017/848'])
    expect(sourceLinks({ ...base, url: 'javascript:alert(1)', finnish_url: null })).toEqual([])
    expect(sourceLinks({ ...base, url: 'https://a.fi/x', finnish_url: 'https://a.fi/x' })).toEqual(['https://a.fi/x'])
    expect(sourceLinks(base)).toEqual([])
  })

  it('names the publisher', () => {
    expect(sourceLinkLabel('https://www.finlex.fi/fi/lainsaadanto/saadoskokoelma/2017/241')).toBe('Finlex: legal text (Finnish)')
    expect(sourceLinkLabel('https://ym.fi/documents/x.pdf')).toBe('Ministry of the Environment (English)')
    expect(sourceLinkLabel('https://example.org/rule')).toBe('example.org')
  })
})
