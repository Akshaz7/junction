import { describe, expect, it } from 'vitest';
import { BoxGeometry, Group, Mesh, MeshStandardMaterial, Vector3 } from 'three';
import { createScene, disposeScene, type SceneManifest } from '../scene';
import { createEditLayer } from '../edits';
import { applyCommand, emptyCommandState } from '../commands';
import { createHighlightController } from '../highlight';

function fixture() {
  const root = new Group();
  root.rotation.y = Math.PI / 2;
  const surface = new MeshStandardMaterial({ color: '#222222' });
  const wall = new Mesh(new BoxGeometry(1, 2, 0.2), surface); wall.name = 'wall';
  const door = new Mesh(new BoxGeometry(1, 2, 0.2), surface); door.name = 'door';
  root.add(wall, door);
  const manifest: SceneManifest = { doc_id: 'generated-for-demo', glb: 'scene.glb', usdz: null, units: 'm', up: 'Y', origin_offset_m: [0, 0, 0], storeys: [], items: {
    wall: { node: 'wall', kind: 'wall', bbox_m: null, storey: null, usd_name: 'wall' },
    door: { node: 'door', kind: 'door', bbox_m: null, storey: null, usd_name: 'door' },
  } };
  const scene = createScene(manifest, { scene: root, parser: { associations: new Map(), json: {} } } as Parameters<typeof createScene>[1]);
  let commands = emptyCommandState();
  const layer = createEditLayer(scene, { apply: (cmd) => { commands = applyCommand(commands, cmd); }, hidden: () => [...commands.hidden] });
  return { layer, wall, door, manifest, scene, surface, commands: () => commands,
    external(command: Parameters<typeof applyCommand>[1]) {
      layer.recordCommand(command, commands);
      commands = applyCommand(commands, command);
    },
  };
}

describe('local edit layer', () => {
  it('Undo reverts only the last panel removal and retains an earlier one', () => {
    const { layer, scene, commands } = fixture();
    layer.remove('wall'); layer.remove('door');
    expect(commands().hidden.size).toBe(2);
    expect(layer.undo()).toMatchObject({ op: 'restore', item_ids: ['door'] });
    expect([...commands().hidden]).toEqual(['wall']);
    layer.undo();
    expect([...commands().hidden]).toEqual([]);
    layer.dispose(); disposeScene(scene);
  });

  it('records a typed removal for the same Undo button', () => {
    const { layer, scene, commands, external } = fixture();
    layer.remove('wall');
    external({ op: 'hide', item_ids: ['door'] });
    expect([...commands().hidden]).toEqual(['wall', 'door']);
    expect(layer.state().undoCount).toBe(2);
    expect(layer.undo()).toMatchObject({ op: 'restore', item_ids: ['door'] });
    expect([...commands().hidden]).toEqual(['wall']);
    layer.dispose(); disposeScene(scene);
  });

  it('retains Undo when the chat snapshot arrives before the matching command socket event', () => {
    const { layer, scene, commands } = fixture();
    layer.remove('wall');
    const before = commands();
    const command = { op: 'hide' as const, item_ids: ['door'] };
    const snapshot = applyCommand(before, command);
    layer.recordState(before, snapshot);
    // The socket command is a no-op after the snapshot and must not consume another Undo.
    layer.recordCommand(command, snapshot);
    expect(layer.state().undoCount).toBe(2);
    layer.undo();
    expect([...commands().hidden]).toEqual(['wall']);
    layer.undo();
    expect([...commands().hidden]).toEqual([]);
    layer.dispose(); disposeScene(scene);
  });
  it('snaps world floor movement through a rotated parent and undoes multiple moves without altering the manifest', () => {
    const { layer, wall, manifest, scene } = fixture();
    const source = JSON.stringify(manifest);
    layer.move('wall', wall.position.clone(), 0.26, -0.14, false);
    expect(layer.state().undoCount).toBe(0);
    expect(wall.getWorldPosition(new Vector3()).x).toBeCloseTo(0.3);
    // A cancelled preview restores through the caller; commit starts at the original position.
    layer.move('wall', new Vector3(), 0.26, -0.14, true);
    const first = wall.position.clone();
    layer.move('wall', first, 0.21, 0.04, true);
    expect(wall.getWorldPosition(new Vector3()).x).toBeCloseTo(0.5);
    layer.undo(); expect(wall.position.toArray()).toEqual(first.toArray());
    layer.undo(); expect(wall.position.length()).toBe(0);
    expect(layer.state().moved).toEqual({});
    expect(JSON.stringify(manifest)).toBe(source);
    layer.dispose(); disposeScene(scene);
  });

  it('shares hide/restore commands, preserves other hidden items, and resets all local edit types', () => {
    const { layer, wall, manifest, surface, scene, commands } = fixture();
    layer.remove('door');
    expect(commands().hidden.has('door')).toBe(true);
    expect(layer.remove('door')).toBeNull();
    expect(layer.changeMaterial('door', 'Glass')).toBeNull();
    layer.changeMaterial('wall', 'Concrete');
    expect(wall.material).not.toBe(surface);
    expect(surface.color.getHexString()).toBe('222222');
    layer.changeMaterial('wall', 'Timber frame');
    layer.move('wall', wall.position.clone(), 0.2, 0.5, true);
    expect(layer.state().materials.wall).toBe('Timber frame');
    expect(manifest.items.wall).not.toHaveProperty('material');
    expect(layer.reset()?.op).toBe('reset');
    expect(commands().hidden.has('door')).toBe(false);
    expect(wall.material).toBe(surface);
    expect(wall.position.length()).toBe(0);
    expect(layer.state()).toEqual({ undoCount: 0, moved: {}, moveDelta: {}, materials: {} });
    layer.dispose(); disposeScene(scene);
  });

  it('reset does not resurrect swapped wall materials when restoring a door rebuilds command highlights', () => {
    const { scene, wall, surface } = fixture();
    const highlights = createHighlightController(scene);
    let state = emptyCommandState();
    const layer = createEditLayer(scene, {
      hidden: () => [...state.hidden],
      apply(command) {
        state = applyCommand(state, command);
        highlights.highlight(['door']);
      },
    });
    layer.changeMaterial('wall', 'Timber frame');
    layer.remove('door');
    // The viewer unwinds current interaction materials before a local edit.
    highlights.clearHighlight();
    layer.reset();
    highlights.clearHighlight();
    expect(wall.material).toBe(surface);
    expect(layer.state().materials).toEqual({});
    layer.dispose(); disposeScene(scene);
  });
});
