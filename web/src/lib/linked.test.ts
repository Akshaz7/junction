import { describe, expect, it } from 'vitest'
import { LinkedApi, placeEvidence, propertyValue, type LinkedItem } from './linked'

const fixture: LinkedItem = {
  item_id: 'door/one', kind: 'door', tag: 'D15', name: 'Door 18', storey: 'Basement', type_name: 'Double door',
  props: { material: 'Air gap', is_external: false, fire_rating: null, nested: { rating: 'EI30' } },
  places: [
    { doc_id: 'ifc__ac20', page: 2, bbox_px: [10, 20, 30, 40], storey: 'Basement' },
    { doc_id: 'detail__doors', page: 4, bbox_px: null, storey: null },
  ],
}

describe('linked drawing references', () => {
  it('loads item IDs and tags via their distinct encoded endpoints, preserving the server properties and places', async () => {
    const paths: string[] = []
    const controller = new AbortController()
    const api = new LinkedApi(async (path, init) => {
      paths.push(String(path))
      expect(init?.signal).toBe(controller.signal)
      return Response.json(fixture)
    })
    expect(await api.get('ifc/ac20', fixture.item_id, controller.signal)).toEqual(fixture)
    expect(await api.get('ifc/ac20', 'D 15', controller.signal, true)).toEqual(fixture)
    expect(paths).toEqual(['/api/docs/ifc%2Fac20/items/door%2Fone', '/api/docs/ifc%2Fac20/tags/D%2015'])
  })
  it('reports absent references and network failures instead of substituting generated details', async () => {
    await expect(new LinkedApi(async () => new Response('', { status: 404 })).get('doc', 'missing')).rejects.toThrow('No item details')
    await expect(new LinkedApi(async () => new Response('', { status: 503 })).get('doc', 'door')).rejects.toThrow('(503)')
    const controller = new AbortController()
    controller.abort()
    await expect(new LinkedApi(async (_path, init) => { init?.signal?.throwIfAborted(); return Response.json(fixture) }).get('doc', 'door', controller.signal)).rejects.toThrow()
  })
  it('focuses the selected location and never projects a previous page box onto a location without coordinates', () => {
    const first = placeEvidence(fixture.places[0], fixture)
    expect(first.regions).toEqual([{ id: fixture.item_id, label: 'D15', bbox: [10, 20, 30, 40], text: false }])
    expect(first.sources[0].itemIds).toEqual([fixture.item_id])
    const other = placeEvidence(fixture.places[1], fixture)
    expect(other.regions).toEqual([])
    expect(other.sources[0].bbox).toBeNull()
    expect(placeEvidence({ ...fixture.places[0], bbox_px: [NaN, 0, 0, 0] }, fixture).regions).toEqual([])
  })
  it('keeps false, zero and structured IFC property values readable', () => {
    expect(Object.values(fixture.props).map(propertyValue)).toEqual(['Air gap', 'false', 'Not supplied', '{"rating":"EI30"}'])
    expect(propertyValue(0)).toBe('0')
  })
})
