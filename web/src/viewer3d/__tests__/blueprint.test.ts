import { describe, expect, it } from 'vitest';
import { classifyRoom, fitRoomLabel, formatElevation, roomLabelText } from '../blueprint';

describe('blueprint rules', () => {
  it('tints wet rooms bluish, kitchens warm, the rest neutral', () => {
    expect(classifyRoom({ name: 'WC', props: null })).toBe('wet');
    expect(classifyRoom({ name: 'Bad', props: null })).toBe('wet');
    expect(classifyRoom({ name: 'x', props: { room_type: 'bathroom' } })).toBe('wet');
    expect(classifyRoom({ name: 'Küche', props: null })).toBe('kitchen');
    expect(classifyRoom({ name: 'Besprechungsraum I', props: null })).toBe('neutral');
    expect(classifyRoom({ name: null, props: null })).toBe('neutral');
  });
  it('labels carry the name and the area only when the data has one', () => {
    expect(roomLabelText({ name: 'Hall', props: { area_m2: 23.94 } })).toEqual({ name: 'Hall', area: '23.9 m²' });
    expect(roomLabelText({ name: 'Hall', props: {} })).toEqual({ name: 'Hall', area: null });
    expect(roomLabelText({ name: null, props: null })).toEqual({ name: null, area: null });
  });
  it('hides labels in rooms narrower than 1.2 m and shrinks text to fit', () => {
    expect(fitRoomLabel(1.0, 5, 3).show).toBe(false);
    const fit = fitRoomLabel(4, 3, 3);
    expect(fit.show).toBe(true);
    expect(fit.width).toBeLessThanOrEqual(4 * 0.9 + 1e-9);
    expect(fitRoomLabel(1.5, 6, 3).rotated).toBe(true);
  });
  it('formats elevations with a signed minus', () => {
    expect(formatElevation(-3)).toBe('−3.00 m');
    expect(formatElevation(0)).toBe('+0.00 m');
    expect(formatElevation(3)).toBe('+3.00 m');
  });
});
