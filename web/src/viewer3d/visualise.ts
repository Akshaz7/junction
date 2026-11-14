import type { SceneCommand } from './commands';

/** The subset of CONTRACT 5.7 needed by the button, compatible with a full Answer. */
export interface VisualiseAnswer {
  doc_ids: readonly string[];
  evidence: {
    scene: { doc_id: string; highlight_item_ids: readonly string[]; camera_target_item_id?: string | null; commands?: readonly SceneCommand[] };
    boxes: readonly { item_id: string; label: string }[];
  };
}

export function answerToVisualise(answer: VisualiseAnswer) {
  const highlight = [...new Set(answer.evidence.scene.highlight_item_ids)];
  const selected = new Set(highlight);
  const labels: Record<string, string> = {};
  for (const box of answer.evidence.boxes) {
    // Repeated page boxes retain their first citation number.
    if (selected.has(box.item_id) && !Object.hasOwn(labels, box.item_id)) labels[box.item_id] = box.label;
  }
  return {
    docId: answer.evidence.scene.doc_id || answer.doc_ids[0] || '',
    highlight,
    labels,
    cameraTargetItemId: answer.evidence.scene.camera_target_item_id ?? undefined,
    ...(answer.evidence.scene.commands ? { commands: answer.evidence.scene.commands } : {}),
  };
}
