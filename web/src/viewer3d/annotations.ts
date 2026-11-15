import { roomTypeLabel } from './blueprint';
import { Vector3, type Camera } from 'three';
import { CSS2DObject } from 'three/examples/jsm/renderers/CSS2DRenderer.js';
import { itemBounds } from './highlight';
import { itemIdForObject, type LoadedScene } from './scene';

export interface LabelAnchor { id: string; x: number; y: number; width: number; height: number }
export interface LabelPlacement { id: string; x: number; y: number; width: number; height: number }

/** Screen-space packing, stable by position and identity. Crowded labels are omitted. */
export function placeLabels(anchors: readonly LabelAnchor[], width: number, height: number): LabelPlacement[] {
  const placed: LabelPlacement[] = [];
  const gap = 6;
  for (const anchor of [...anchors].sort((a, b) => a.y - b.y || a.x - b.x || a.id.localeCompare(b.id))) {
    // A leader only refers to an item actually inside this viewport.
    if (anchor.x < 0 || anchor.x > width || anchor.y < 0 || anchor.y > height) continue;
    let result: LabelPlacement | undefined;
    // Above the item first; below it when the item is near the top edge of the viewport.
    for (let attempt = 0; attempt < 8 && !result; attempt++) {
      const row = attempt % 4;
      const below = attempt >= 4;
      for (const column of [0, -1, 1]) {
        const x = Math.max(gap, Math.min(width - anchor.width - gap,
          anchor.x - anchor.width / 2 + column * (anchor.width + gap)));
        const y = below ? anchor.y + 30 + row * (anchor.height + gap) : anchor.y - 30 - anchor.height - row * (anchor.height + gap);
        if (x < gap || x + anchor.width > width - gap || y < gap || y + anchor.height > height - gap) continue;
        const candidate = { id: anchor.id, x, y, width: anchor.width, height: anchor.height };
        if (!placed.some((other) => x < other.x + other.width + gap && x + anchor.width + gap > other.x
          && y < other.y + other.height + gap && y + anchor.height + gap > other.y)) result = candidate;
        if (result) break;
      }
    }
    if (result) placed.push(result);
  }
  return placed;
}

export function createItemAnnotation(scene: LoadedScene, id: string, text: string): CSS2DObject | null {
  const object = scene.items.get(id);
  const bounds = itemBounds(scene, [id]);
  if (!object || bounds.isEmpty()) return null;
  const element = document.createElement('div');
  element.className = 'viewer3d-annotation';
  element.dataset.itemId = id;
  const pill = document.createElement('div');
  pill.className = 'viewer3d-label-pill';
  const number = document.createElement('span');
  number.className = 'viewer3d-item-label';
  number.dataset.itemId = id;
  number.textContent = text;
  number.setAttribute('aria-label', `Item ${text}: ${id}`);
  const kind = document.createElement('span');
  kind.className = 'viewer3d-label-kind';
  const it = scene.manifest.items[id];
  kind.textContent = it.kind === 'room' ? roomTypeLabel(it) : it.kind;
  pill.append(number, kind);
  const leader = document.createElement('span');
  leader.className = 'viewer3d-label-leader';
  leader.setAttribute('aria-hidden', 'true');
  element.append(leader, pill);
  const label = new CSS2DObject(element);
  const top = bounds.getCenter(new Vector3());
  top.y = bounds.max.y;
  label.position.copy(object.worldToLocal(top));
  object.add(label);
  return label;
}

/** Called after CSS2DRenderer every frame, including orbit, resize, edits and rise. */
export interface Blocker { x: number; y: number; width: number; height: number }

/** Screen rects (relative to the stage) of UI cards and panels that scene captions must never cover. */
export function uiBlockers(stage: HTMLElement | null): Blocker[] {
  if (!stage) return [];
  const origin = stage.getBoundingClientRect();
  const out: Blocker[] = [];
  for (const el of stage.querySelectorAll<HTMLElement>('.viewer3d-item-card, .viewer3d-findings-card, .viewer3d-advisor-card, .kind-legend-3d, .viewer3d-approx')) {
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden') {
      out.push({ x: r.left - origin.left, y: r.top - origin.top, width: r.width, height: r.height });
    }
  }
  return out;
}

/** Keep a DOM label fully inside the stage by nudging it after CSS2DRenderer positioned it. */
export function clampLabelInside(element: HTMLElement, stage: HTMLElement, margin = 4): void {
  const r = element.getBoundingClientRect();
  if (!r.width) return;
  const s = stage.getBoundingClientRect();
  const dx = r.left < s.left + margin ? s.left + margin - r.left : r.right > s.right - margin ? s.right - margin - r.right : 0;
  const dy = r.top < s.top + margin ? s.top + margin - r.top : r.bottom > s.bottom - margin ? s.bottom - margin - r.bottom : 0;
  if (dx || dy) element.style.transform += ` translate(${dx}px, ${dy}px)`;
}

export function layoutAnnotations(labels: readonly CSS2DObject[], scene: LoadedScene, camera: Camera, width: number, height: number, blockers: readonly Blocker[] = []): void {
  const anchors: LabelAnchor[] = [];
  for (const label of labels) {
    const element = label.element;
    const id = element.dataset.itemId!;
    const projected = label.getWorldPosition(new Vector3()).project(camera);
    const visible = itemIdForObject(scene, label) !== null && projected.z >= -1 && projected.z <= 1;
    const pill = element.querySelector<HTMLElement>('.viewer3d-label-pill')!;
    // CSS2DRenderer can hide an ancestor; measure again when it becomes visible.
    if (visible) anchors.push({ id, x: (projected.x + 1) * width / 2, y: (1 - projected.y) * height / 2,
      width: pill.offsetWidth, height: pill.offsetHeight });
    element.style.visibility = 'hidden';
  }
  const placements = new Map(placeLabels(anchors, width, height).map((placement) => [placement.id, placement]));
  for (const label of labels) {
    const element = label.element;
    const placement = placements.get(element.dataset.itemId!);
    if (!placement) continue;
    const anchorPt = anchors.find((candidate) => candidate.id === placement.id)!;
    // Hide a caption (pill or leader tip) that would sit on a card or panel.
    if (blockers.some((b) => (placement.x < b.x + b.width && placement.x + placement.width > b.x
      && placement.y < b.y + b.height && placement.y + placement.height > b.y)
      || (anchorPt.x > b.x && anchorPt.x < b.x + b.width && anchorPt.y > b.y && anchorPt.y < b.y + b.height))) continue;
    const anchor = anchors.find((candidate) => candidate.id === placement.id)!;
    element.style.visibility = 'visible';
    element.style.transform = `translate(${placement.x}px, ${placement.y}px)`;
    const leader = element.querySelector<HTMLElement>('.viewer3d-label-leader')!;
    const fromX = placement.width / 2;
    const fromY = placement.height;
    const dx = anchor.x - placement.x - fromX;
    const dy = anchor.y - placement.y - fromY;
    Object.assign(leader.style, { left: `${fromX}px`, top: `${fromY}px`, width: `${Math.hypot(dx, dy)}px`,
      transform: `rotate(${Math.atan2(dy, dx)}rad)` });
  }
}
