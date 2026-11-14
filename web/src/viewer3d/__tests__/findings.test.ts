import { afterEach, describe, expect, it, vi } from 'vitest';
import { BoxGeometry, Group, Mesh, MeshBasicMaterial, PerspectiveCamera, Raycaster, Sprite, Vector2, Vector3 } from 'three';
import { createFindingsLayer, findingColors, groupFindings, type Finding } from '../findings';
import type { LoadedScene } from '../scene';
import { createLiveHighlightClient, decodeLiveMessage } from '../liveHighlight';

const finding: Finding = { id: 'check-1', doc_id: 'demo', rule_id: 'demo-rule', item_ids: ['door-001'],
  severity: 'suggestion', message: '', detail: {}, rule: { id: 'demo-rule', text: 'Generated for demo.' } };
afterEach(() => vi.unstubAllGlobals());

describe('findings anchors and live notifications', () => {
  it('stacks distinct findings on their first item, without substituting later or foreign items', () => {
    const scene: LoadedScene = {
      manifest: { doc_id: 'demo', glb: 'demo.glb', usdz: null, units: 'm', up: 'Y',
        origin_offset_m: [0, 0, 0], storeys: [], items: {} },
      items: new Map([['door-001', new Group()]]), root: new Group(), missingItemIds: [],
      originalVisibility: new Map(), itemIdsByObject: new Map(),
    };
    const second = { ...finding, id: 'check-2', severity: 'violation' as const };
    const groups = groupFindings([finding, finding, second,
      { ...finding, id: 'foreign', doc_id: 'another' },
      { ...finding, id: 'missing', item_ids: ['missing', 'door-001'] },
      { ...finding, id: 'empty', item_ids: [] }], scene);
    expect([...groups.keys()]).toEqual(['door-001']);
    expect(groups.get('door-001')).toEqual([finding, second]);
    expect(Object.keys(findingColors).sort()).toEqual(['info', 'suggestion', 'violation']);
  });

  it('accepts only complete findings.updated events and keeps the shared socket alive for the layer', () => {
    const event = { type: 'findings.updated', doc_id: 'demo', count: 2 };
    expect(decodeLiveMessage(JSON.stringify(event))).toEqual(event);
    for (const invalid of [{ ...event, count: -1 }, { ...event, count: '2' }, { ...event, doc_id: '' }]) {
      expect(decodeLiveMessage(JSON.stringify(invalid))).toBeNull();
    }
    const socket = Object.assign(new EventTarget(), { readyState: 1, close: vi.fn() });
    const connect = vi.fn(() => socket as unknown as WebSocket);
    const client = createLiveHighlightClient({ url: 'ws://demo/ws', connect });
    const stopHighlight = client.onHighlight(vi.fn());
    const callback = vi.fn(); const stopFindings = client.onFindingsUpdated(callback);
    socket.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(event) }));
    expect(callback).toHaveBeenCalledExactlyOnceWith(event);
    expect(connect).toHaveBeenCalledOnce();
    stopHighlight(); expect(socket.close).not.toHaveBeenCalled();
    stopFindings(); expect(socket.close).toHaveBeenCalledOnce();
  });

  it('anchors stacked sprites above geometry, keeps their size across zooms, follows moves, and disposes resources', () => {
    const context = { beginPath: vi.fn(), arc: vi.fn(), fill: vi.fn(), stroke: vi.fn(), moveTo: vi.fn(),
      lineTo: vi.fn(), fillText: vi.fn() };
    class Element {
      style = {}; dataset = {}; parentNode = null;
      ownerDocument = { defaultView: { Element } };
      setAttribute = vi.fn(); remove = vi.fn(); onclick?: () => void;
      getContext = () => context;
    }
    vi.stubGlobal('document', { createElement: () => new Element() });
    const root = new Group();
    const object = new Mesh(new BoxGeometry(2, 2, 2), new MeshBasicMaterial()); root.add(object);
    const scene: LoadedScene = {
      manifest: { doc_id: 'demo', glb: '', usdz: null, units: 'm', up: 'Y', origin_offset_m: [0, 0, 0], storeys: [], items: {} },
      root, items: new Map([['door-001', object]]), itemIdsByObject: new Map(), originalVisibility: new Map(), missingItemIds: [],
    };
    const select = vi.fn(); const layer = createFindingsLayer(scene, select);
    const entries = [finding, { ...finding, id: 'check-2', severity: 'violation' as const }];
    layer.set(entries);
    expect(layer.root.children.filter((child) => child instanceof Sprite)).toHaveLength(1);
    expect(context.fillText).toHaveBeenCalledWith('2', 64, 54);
    const hit = layer.root.children[1] as unknown as { element: Element };
    hit.element.onclick!(); expect(select).toHaveBeenCalledWith(entries);
    const camera = new PerspectiveCamera(45, 800 / 600, .01, 1000);
    const rect = { left: 20, top: 30, width: 800, height: 600 } as DOMRect;
    const project = (point: Vector3) => {
      point.project(camera);
      return [20 + (point.x + 1) * 400, 30 + (1 - point.y) * 300];
    };
    for (const distance of [12, 40]) {
      camera.position.set(0, distance / 2, distance); camera.lookAt(0, 0, 0);
      // A finding on a hidden floor must still be discoverable in a cutaway.
      object.visible = false;
      layer.update(camera, 600);
      const pins = layer.state(camera, rect);
      const top = project(new Vector3(0, 1, 0));
      expect(pins.map((pin) => pin.id)).toEqual(['check-1', 'check-2']);
      expect(pins[0].screen_xy![0]).toBeCloseTo(top[0]);
      expect(top[1] - pins[0].screen_xy![1]).toBeCloseTo(26);
      const sprite = layer.root.children[0] as Sprite;
      const upper = project(sprite.position.clone().add(new Vector3(0, sprite.scale.y, 0).applyQuaternion(camera.quaternion)));
      expect(pins[0].screen_xy![1] - upper[1]).toBeCloseTo(40);
      // Real sprite picking must work before a render, at every zoom, even
      // above an item hidden by the cutaway. Outside the 40px pin must miss.
      const raycaster = new Raycaster();
      const [x, y] = pins[0].screen_xy!;
      select.mockClear();
      raycaster.setFromCamera(new Vector2((x - rect.left) / rect.width * 2 - 1, 1 - (y - rect.top) / rect.height * 2), camera);
      expect(layer.select(raycaster)).toBe(true);
      expect(select).toHaveBeenCalledExactlyOnceWith(entries);
      raycaster.setFromCamera(new Vector2((x + 24 - rect.left) / rect.width * 2 - 1, 1 - (y - rect.top) / rect.height * 2), camera);
      expect(layer.select(raycaster)).toBe(false);
      expect(select).toHaveBeenCalledTimes(1);
    }
    object.position.x = 3; layer.update(camera, 600);
    expect(layer.state(camera, rect)[0].screen_xy![0]).toBeCloseTo(project(new Vector3(3, 1, 0))[0]);
    camera.lookAt(0, 0, 100); layer.update(camera, 600);
    expect(layer.state(camera, rect).every((pin) => pin.screen_xy === null)).toBe(true);
    const raycaster = new Raycaster(); raycaster.setFromCamera(new Vector2(), camera);
    expect(layer.select(raycaster)).toBe(false);
    const sprite = layer.root.children[0] as Sprite;
    const disposeMap = vi.spyOn(sprite.material.map!, 'dispose');
    const disposeMaterial = vi.spyOn(sprite.material, 'dispose');
    layer.dispose();
    expect(disposeMap).toHaveBeenCalledOnce(); expect(disposeMaterial).toHaveBeenCalledOnce();
    expect(layer.root.children).toHaveLength(0);
    object.geometry.dispose(); object.material.dispose();
  });
});
