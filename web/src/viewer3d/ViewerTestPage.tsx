import { useState } from 'react';
import { Viewer3D } from './Viewer3D';
import type { Viewer } from './viewer';
import type { HighlightState } from './highlight';

/** The LEAD mounts this page at /#/viewer-test; production callers pass their API URL. */
export function ViewerTestPage() {
  const [viewer, setViewer] = useState<Viewer | null>(null);
  const [highlightState, setHighlightState] = useState<HighlightState>({ highlighted: [], dimmed: 0, labels: {} });

  function highlightRandom() {
    if (!viewer?.scene) return;
    // Sample without replacement; use only resolved, rendered contract items.
    const candidates = [...viewer.scene.items.keys()];
    const ids: string[] = [];
    while (ids.length < 3 && candidates.length) {
      ids.push(candidates.splice(Math.floor(Math.random() * candidates.length), 1)[0]);
    }
    viewer.highlight(ids, { labels: Object.fromEntries(ids.map((id, index) => [id, String(index + 1)])) });
    setHighlightState(viewer.getHighlightState());
  }

  return <main className="viewer3d-test-page">
    <header>
      <h1>DigitalHub — 3D viewer</h1>
      <p>Copyright (c) 2020 RWTH Aachen University — E3D Institute of Energy Efficiency and Sustainable Building · MIT</p>
      <div className="viewer3d-test-actions">
        <button type="button" disabled={!viewer} onClick={highlightRandom}>Highlight 3 random items</button>
        <button type="button" disabled={!viewer} onClick={() => {
          viewer?.clearHighlight();
          if (viewer) setHighlightState(viewer.getHighlightState());
        }}>Clear highlight</button>
        <output aria-label="Highlight state">{JSON.stringify(highlightState)}</output>
      </div>
    </header>
    <Viewer3D sceneUrl={`${import.meta.env.BASE_URL}fixtures/digital_hub/scene.json`} onReady={setViewer} />
  </main>;
}

export default ViewerTestPage;
