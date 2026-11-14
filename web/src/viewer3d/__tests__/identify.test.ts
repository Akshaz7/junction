import { describe, expect, it } from 'vitest';
import { buildItemDetails, indexElements, type IFCElement } from '../identify';
import type { SceneManifest } from '../scene';

const manifest: SceneManifest = {
  doc_id: 'example', glb: 'scene.glb', usdz: null, units: 'm', up: 'Y',
  origin_offset_m: [0, 0, 0], storeys: ['Ground'],
  items: {
    'door-001': {
      node: 'door-001', usd_name: 'i_example', kind: 'door', storey: 'Ground',
      bbox_m: [[0, 0, 0], [1, 2, 0.1]],
    },
  },
};
const element: IFCElement = {
  item_id: 'door-001', name: 'Entrance door', kind: 'door', ifc_class: 'IfcDoor',
  predefined_type: 'DOOR', type_name: 'Single swing', storey: { name: 'Ground', elevation_m: 0 },
  quantities: { width_m: 1, height_m: 2.1, area_m2: 2.1, volume_m3: 0.1 },
  props: { material: 'Timber', fire_rating: 'EI30', is_external: false },
};

describe('item card model', () => {
  it('shows the document tag in item details independently of answer citation labels', () => {
    const tagged = { ...manifest, items: { 'door-001': { ...manifest.items['door-001'], tag: 'D3' } } };
    expect(buildItemDetails(tagged, 'door-001', element)?.fields).toContainEqual({ label: 'Tag', value: 'D3' });
  });

  it('joins scene identity with IFC names, storey, measured quantities and properties', () => {
    const details = buildItemDetails(manifest, 'door-001', element)!;
    expect(details.name).toBe('Entrance door');
    expect(details.hasElement).toBe(true);
    expect(Object.fromEntries(details.fields.map(({ label, value }) => [label, value]))).toEqual({
      Kind: 'door', Storey: 'Ground', 'IFC class': 'IfcDoor', Type: 'Single swing',
      'Predefined type': 'DOOR', Width: '1 m', Height: '2.1 m', Area: '2.1 m²',
      Volume: '0.1 m³', Material: 'Timber', 'Fire rating': 'EI30', External: 'No',
    });
  });

  it('falls back to the scene without inventing dimensions from bounding boxes', () => {
    expect(buildItemDetails(manifest, 'door-001')).toEqual({
      item_id: 'door-001', name: 'door-001', hasElement: false,
      fields: [{ label: 'Kind', value: 'door' }, { label: 'Storey', value: 'Ground' },
        { label: 'Type', value: 'door' }, { label: 'Size', value: 'Not available' }],
    });
    expect(buildItemDetails(manifest, 'missing', element)).toBeNull();
    expect(buildItemDetails(manifest, 'door-001', { ...element, item_id: 'different' })?.hasElement).toBe(false);
  });

  it('preserves zero and true, omits null/non-finite quantities, and handles missing storeys', () => {
    const scene = { ...manifest, items: { 'door-001': { ...manifest.items['door-001'], storey: null } } };
    const details = buildItemDetails(scene, 'door-001', {
      item_id: 'door-001', name: ' ', quantities: { width_m: null, height_m: NaN, area_m2: 0 },
      props: { is_external: true, material: null },
    })!;
    expect(details.name).toBe('door-001');
    expect(details.fields).toEqual([
      { label: 'Kind', value: 'door' }, { label: 'Storey', value: 'Not available' },
      { label: 'Type', value: 'door' }, { label: 'Area', value: '0 m²' }, { label: 'External', value: 'Yes' },
    ]);
  });

  it('indexes the pipeline envelope and plain entry arrays by exact item ID', () => {
    expect(indexElements({ doc_id: 'example', elements: [element] }).get('door-001')).toEqual(element);
    expect(indexElements([null, {}, element]).size).toBe(1);
    expect(() => indexElements({ status: 'not_built' })).toThrow('Invalid IFC element index');
  });
});
