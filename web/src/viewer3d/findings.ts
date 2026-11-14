import { CanvasTexture, Group, PerspectiveCamera, Sprite, SpriteMaterial, Vector3, type Raycaster } from 'three';
import { CSS2DObject } from 'three/examples/jsm/renderers/CSS2DRenderer.js';
import type { LoadedScene } from './scene';
import { itemBounds } from './highlight';

/** Exact severities and rule fields returned by server/findings_routes.py. */
export type FindingSeverity = 'info' | 'suggestion' | 'violation';
export interface Finding {
  id: string;
  doc_id: string;
  rule_id: string;
  item_ids: string[];
  severity: FindingSeverity;
  message: string;
  detail: Record<string, unknown>;
  rule: { id: string; text: string; source_title?: string | null; section?: string | null;
    url?: string | null; quote?: string | null; translation?: string | null };
}
export interface FindingPinState {
  id: string;
  item_id: string;
  severity: FindingSeverity;
  /** Viewport client pixels, matching pointer events. Null when clipped. */
  screen_xy: [number, number] | null;
}
export const findingColors: Record<FindingSeverity, string> = {
  violation: '#c93434', suggestion: '#b76c05', info: '#246baa',
};
const priority: Record<FindingSeverity, number> = { info: 0, suggestion: 1, violation: 2 };

export function groupFindings(findings: readonly Finding[], scene: LoadedScene): Map<string, Finding[]> {
  const groups = new Map<string, Finding[]>();
  const seen = new Set<string>();
  for (const finding of findings) {
    const id = finding.item_ids[0];
    if (finding.doc_id !== scene.manifest.doc_id || !id || !scene.items.has(id) || seen.has(finding.id)) continue;
    seen.add(finding.id);
    const group = groups.get(id) ?? [];
    group.push(finding); groups.set(id, group);
  }
  return groups;
}

/** Sprites face the camera; a CSS2D hit target adds keyboard/touch access. */
export function createFindingsLayer(scene: LoadedScene, onSelect: (findings: Finding[]) => void) {
  const root = new Group();
  const pins: { findings: Finding[]; id: string; anchor: Vector3; sprite: Sprite; hit: CSS2DObject }[] = [];
  function clear() {
    for (const { sprite, hit } of pins) {
      sprite.material.map?.dispose(); sprite.material.dispose();
      hit.element.remove();
    }
    pins.length = 0; root.clear();
  }
  function set(findings: readonly Finding[]) {
    clear();
    for (const [id, entries] of groupFindings(findings, scene)) {
      const object = scene.items.get(id)!;
      const bounds = itemBounds(scene, [id]);
      if (bounds.isEmpty()) continue;
      const anchor = bounds.getCenter(new Vector3());
      anchor.y = bounds.max.y;
      object.worldToLocal(anchor);
      const severity = entries.reduce((a, b) => priority[b.severity] > priority[a] ? b.severity : a, entries[0].severity);
      const canvas = document.createElement('canvas'); canvas.width = 128; canvas.height = 128;
      const ctx = canvas.getContext('2d')!;
      // Stacked rings distinguish several checks anchored to the same item.
      for (let offset = entries.length > 1 ? 10 : 0; offset >= 0; offset -= 10) {
        ctx.beginPath(); ctx.arc(64 + offset, 54 - offset, 40, 0, Math.PI * 2);
        ctx.fillStyle = findingColors[severity]; ctx.fill();
        ctx.lineWidth = 7; ctx.strokeStyle = '#fff'; ctx.stroke();
      }
      ctx.beginPath(); ctx.moveTo(48, 87); ctx.lineTo(64, 118); ctx.lineTo(80, 87);
      ctx.fillStyle = findingColors[severity]; ctx.fill();
      ctx.fillStyle = '#fff'; ctx.font = 'bold 48px system-ui'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText(entries.length > 1 ? String(entries.length) : '!', 64, 54);
      const texture = new CanvasTexture(canvas);
      const sprite = new Sprite(new SpriteMaterial({ map: texture, depthTest: false, depthWrite: false }));
      sprite.renderOrder = 1000;
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'viewer3d-finding-pin';
      button.setAttribute('aria-label', `${entries.length} ${severity} finding${entries.length > 1 ? 's' : ''}: ${id}`);
      button.dataset.itemId = id;
      button.onclick = () => onSelect(entries);
      const hit = new CSS2DObject(button);
      root.add(sprite, hit); pins.push({ findings: entries, id, anchor, sprite, hit });
    }
  }
  function update(camera: PerspectiveCamera, height: number) {
    camera.updateWorldMatrix(true, false);
    for (const pin of pins) {
      const object = scene.items.get(pin.id)!;
      const top = object.localToWorld(pin.anchor.clone());
      const depth = -top.clone().applyMatrix4(camera.matrixWorldInverse).z;
      // Findings remain discoverable above cutaway floors; Show items reveals
      // their storey through the existing highlight path.
      const visible = depth > camera.near && depth < camera.far;
      pin.sprite.visible = pin.hit.visible = visible;
      // Fixed 40 CSS pixels at any orbit distance; 26px above bbox top centre.
      const metresPerPixel = 2 * Math.max(depth, camera.near) * Math.tan(camera.fov * Math.PI / 360) / Math.max(1, height);
      const up = new Vector3(0, 1, 0).applyQuaternion(camera.quaternion);
      pin.sprite.position.copy(top).addScaledVector(up, 26 * metresPerPixel);
      pin.sprite.scale.setScalar(40 * metresPerPixel);
      pin.hit.position.copy(pin.sprite.position);
    }
  }
  function state(camera: PerspectiveCamera, rect: DOMRect): FindingPinState[] {
    return pins.flatMap((pin) => {
      const point = pin.sprite.position.clone().project(camera);
      const visible = pin.sprite.visible && Math.abs(point.x) <= 1 && Math.abs(point.y) <= 1 && Math.abs(point.z) <= 1;
      const screen_xy: [number, number] | null = visible
        ? [rect.left + (point.x + 1) * rect.width / 2, rect.top + (1 - point.y) * rect.height / 2] : null;
      return pin.findings.map((finding) => ({ id: finding.id, item_id: pin.id, severity: finding.severity, screen_xy }));
    });
  }
  function select(raycaster: Raycaster): boolean {
    // Sprite.raycast needs the camera from setFromCamera and current world
    // matrices. Only test visible pins; hidden floors still have visible pins.
    root.updateWorldMatrix(true, true);
    const hits = raycaster.intersectObjects(pins.filter((pin) => pin.sprite.visible).map((pin) => pin.sprite), false);
    const pin = hits.length ? pins.find((entry) => entry.sprite === hits[0].object) : undefined;
    if (!pin) return false;
    onSelect(pin.findings);
    return true;
  }
  return { root, set, update, state, select, dispose() { clear(); root.removeFromParent(); } };
}
