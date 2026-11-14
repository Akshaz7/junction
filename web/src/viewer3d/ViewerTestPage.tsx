import { useEffect, useState } from 'react';
import { Viewer3D } from './Viewer3D';
import type { Viewer } from './viewer';
import type { HighlightState } from './highlight';

/** The LEAD mounts this page at /#/viewer-test; production callers pass their API URL. */
export function ViewerTestPage() {
  const [viewer, setViewer] = useState<Viewer | null>(null);
  const [document, setDocument] = useState('digital_hub');
  const [highlightState, setHighlightState] = useState<HighlightState>({ highlighted: [], dimmed: 0, labels: {} });

  // Only the dedicated dev page exposes the camera for deterministic pointer tests.
  useEffect(() => {
    const target = window as typeof window & { viewer3dTest?: Viewer };
    if (viewer) target.viewer3dTest = viewer;
    return () => { delete target.viewer3dTest; };
  }, [viewer]);

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
      <h1>{document === 'digital_hub' ? 'DigitalHub' : 'AC20'} — 3D viewer</h1>
      <p>{document === 'digital_hub'
        ? 'Copyright (c) 2020 RWTH Aachen University — E3D Institute of Energy Efficiency and Sustainable Building · MIT'
        : 'Institute for Automation and Applied Informatics (IAI) / Karlsruhe Institute of Technology (KIT) · KIT IFC Examples'}</p>
      <div className="viewer3d-test-actions">
        <label htmlFor="viewer3d-document">Document</label>
        <select id="viewer3d-document" value={document} onChange={(event) => {
          setViewer(null);
          setHighlightState({ highlighted: [], dimmed: 0, labels: {} });
          setDocument(event.target.value);
        }}>
          <option value="digital_hub">DigitalHub (offline fixture)</option>
          <option value="ifc_bench__ac20-arc">AC20 (API)</option>
        </select>
        <button type="button" disabled={!viewer} onClick={highlightRandom}>Highlight 3 random items</button>
        <button type="button" disabled={!viewer} onClick={() => {
          viewer?.clearHighlight();
          if (viewer) setHighlightState(viewer.getHighlightState());
        }}>Clear highlight</button>
        <output aria-label="Highlight state">{JSON.stringify(highlightState)}</output>
      </div>
    </header>
    <Viewer3D key={document} {...(document === 'digital_hub'
      ? { sceneUrl: `${import.meta.env.BASE_URL}fixtures/digital_hub/scene.json` }
      : { doc_id: document })} onReady={setViewer} />
  </main>;
}

export default ViewerTestPage;
