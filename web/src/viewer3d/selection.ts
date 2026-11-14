import type { SceneManifest } from './scene';
import type { Viewer } from './viewer';
import { setHover, setSelected } from './link';

/** Use the source kind, across storeys, rather than a colour or a tag prefix. */
export function itemsOfPickedKind(manifest: SceneManifest, id: string): string[] {
  const kind = manifest.items[id]?.kind;
  return kind ? Object.keys(manifest.items).filter((key) => manifest.items[key].kind === kind) : [];
}

export function clearViewerHighlights(viewer: Pick<Viewer, 'applyCommand'>): void {
  setHover(null, '2d');
  setHover(null, '3d');
  setSelected(null, '3d');
  // An empty selection clears answer and command highlights, preserving hides/isolation.
  viewer.applyCommand({ op: 'highlight', item_ids: [] });
}
