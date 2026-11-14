import { useEffect, useState } from 'react';
import { Viewer3D } from './Viewer3D';
import type { Viewer } from './viewer';
import type { HighlightState } from './highlight';
import { VisualiseItButton } from './VisualiseIt';

/** The LEAD mounts this page at /#/viewer-test; production callers pass their API URL. */
export function ViewerTestPage() {
  const [viewer, setViewer] = useState<Viewer | null>(null);
  const [document, setDocument] = useState(() => {
    const requested = new URLSearchParams(window.location.search).get('doc');
    if (requested === 'colorful-11397' || requested === 'cubicasa5k__colorful-11397') return 'colorful-11397';
    return requested === 'ifc_bench__ac20-arc' ? requested : 'digital_hub';
  });
  const [visualiseDocId, setVisualiseDocId] = useState('cubicasa5k__colorful-11397');
  const [visualiseViewer, setVisualiseViewer] = useState<Viewer | null>(null);
  const [highlightState, setHighlightState] = useState<HighlightState>({ highlighted: [], dimmed: 0, labels: {} });

  // Only the dedicated dev page exposes the camera for deterministic pointer tests.
  useEffect(() => {
    const target = window as typeof window & { viewer3dTest?: Viewer };
    if (viewer) target.viewer3dTest = viewer;
    const unsubscribe = viewer?.onHighlightChange(setHighlightState);
    return () => { unsubscribe?.(); delete target.viewer3dTest; };
  }, [viewer]);

  useEffect(() => {
    const target = window as typeof window & { visualise3dTest?: Viewer };
    if (visualiseViewer) target.visualise3dTest = visualiseViewer;
    return () => { delete target.visualise3dTest; };
  }, [visualiseViewer]);

  const fakeIds = Array.from({ length: 5 }, (_, i) => `window-${String(i + 1).padStart(3, '0')}`);
  const fakeAnswer = {
    doc_ids: [visualiseDocId.trim()],
    evidence: {
      scene: { doc_id: visualiseDocId.trim(), highlight_item_ids: fakeIds },
      boxes: fakeIds.map((item_id, i) => ({ item_id, label: String(i + 1) })),
    },
  };

  function highlightRandom() {
    if (!viewer?.scene) return;
    // Sample without replacement; use only resolved, rendered contract items.
    const candidates = [...viewer.scene.items.keys()];
    const ids: string[] = [];
    while (ids.length < 3 && candidates.length) {
      ids.push(candidates.splice(Math.floor(Math.random() * candidates.length), 1)[0]);
    }
    viewer.highlight(ids, { labels: Object.fromEntries(ids.map((id, index) => [id, String(index + 1)])) });
  }

  return <main className="viewer3d-test-page">
    <header>
      <h1>{document === 'digital_hub' ? 'DigitalHub' : document === 'colorful-11397' ? 'CubiCasa colorful-11397' : 'AC20'} — 3D viewer</h1>
      <p>{document === 'digital_hub'
        ? 'Copyright (c) 2020 RWTH Aachen University — E3D Institute of Energy Efficiency and Sustainable Building · MIT'
        : document === 'colorful-11397'
        ? "CubiCasa5K, (c) 2019 CubiCasa. Kalervo, Ylioinas, Häikiö, Karhu, Kannala: 'CubiCasa5K: A Dataset and an Improved Multi-Task Model for Floorplan Image Analysis', SCIA 2019. CC BY-NC-SA 4.0. Extruded heights generated for demo."
        : 'Institute for Automation and Applied Informatics (IAI) / Karlsruhe Institute of Technology (KIT) · KIT IFC Examples'}</p>
      <div className="viewer3d-test-actions">
        <label htmlFor="viewer3d-document">Document</label>
        <select id="viewer3d-document" value={document} onChange={(event) => {
          setViewer(null);
          setHighlightState({ highlighted: [], dimmed: 0, labels: {} });
          setDocument(event.target.value);
        }}>
          <option value="digital_hub">DigitalHub (offline fixture)</option>
          <option value="colorful-11397">CubiCasa colorful-11397 (light offline fixture)</option>
          <option value="ifc_bench__ac20-arc">AC20 (API)</option>
        </select>
        <button type="button" disabled={!viewer} onClick={highlightRandom}>Highlight 3 random items</button>
        <button type="button" disabled={!viewer} onClick={() => {
          viewer?.clearHighlight();
        }}>Clear highlight</button>
        <output aria-label="Highlight state">{JSON.stringify(highlightState)}</output>
      </div>
      <section className="viewer3d-test-visualise" aria-label="Visualise an answer">
        <label htmlFor="viewer3d-visualise-doc">Visualise document ID</label>
        <input id="viewer3d-visualise-doc" value={visualiseDocId}
          onChange={(event) => setVisualiseDocId(event.target.value)} />
        <p>Fake answer — generated for demo: highlight window-001 through window-005 with labels 1–5.</p>
        <p>CubiCasa5K · CC BY-NC-SA · non-commercial use only. Extruded heights are generated for demo.</p>
        <VisualiseItButton answer={fakeAnswer} onReady={setVisualiseViewer} />
      </section>
    </header>
    <Viewer3D key={document} {...(document === 'ifc_bench__ac20-arc'
      ? { doc_id: document }
      : { sceneUrl: `${import.meta.env.BASE_URL}fixtures/${document}/scene.json` })} onReady={setViewer} />
  </main>;
}

export default ViewerTestPage;
