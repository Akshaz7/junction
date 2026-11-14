import { describe, expect, it } from 'vitest';
import { placeLabels, type LabelAnchor } from '../annotations';
import { buildItemDetails } from '../identify';
import type { SceneManifest } from '../scene';

describe('floating evidence labels', () => {
  it('packs dense anchors without overlap, hides overflow, and is independent of traversal order', () => {
    const anchors: LabelAnchor[] = Array.from({ length: 50 }, (_, i) => ({
      id: String(i), x: 120 + i % 3, y: 250 + i % 2, width: 60, height: 38,
    }));
    const placed = placeLabels(anchors, 260, 300);
    expect(placed.length).toBeGreaterThan(1);
    expect(placed.length).toBeLessThan(anchors.length);
    expect(placeLabels([...anchors].reverse(), 260, 300)).toEqual(placed);
    for (const box of placed) {
      expect(box.x).toBeGreaterThanOrEqual(6);
      expect(box.y).toBeGreaterThanOrEqual(6);
      expect(box.x + box.width).toBeLessThanOrEqual(254);
      for (const other of placed) {
        if (other === box) continue;
        expect(box.x + box.width <= other.x || other.x + other.width <= box.x
          || box.y + box.height <= other.y || other.y + other.height <= box.y).toBe(true);
      }
    }
  });

  it('recomputes on viewport changes and omits off-screen or unplaceable labels', () => {
    const anchors = [
      { id: '1', x: 180, y: 200, width: 60, height: 38 },
      { id: '2', x: -10, y: 200, width: 60, height: 38 },
      { id: '3', x: 20, y: 15, width: 60, height: 38 },
    ];
    expect(placeLabels(anchors, 250, 300).map((p) => p.id)).toEqual(['1']);
    expect(placeLabels(anchors, 100, 300)).toEqual([]);
  });
});

it('uses actual scene metadata for callouts without converting bounding extents into product dimensions', () => {
  const manifest = { items: { door: { name: 'Entrance', kind: 'door', storey: 'Ground',
    type_name: 'Single swing', quantities: { width_m: 0.9, height_m: 2.1 },
    bbox_m: [[0, 0, 0], [50, 50, 50]],
  } } } as unknown as SceneManifest;
  const details = buildItemDetails(manifest, 'door')!;
  expect(details.name).toBe('Entrance');
  expect(details.fields).toEqual(expect.arrayContaining([
    { label: 'Type', value: 'Single swing' }, { label: 'Storey', value: 'Ground' },
    { label: 'Width', value: '0.9 m' }, { label: 'Height', value: '2.1 m' },
  ]));
  expect(details.fields.some(({ value }) => value === '50 m')).toBe(false);
});
