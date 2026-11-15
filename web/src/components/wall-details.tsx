import { howMeasured, wallMeasure, type WallDetails as Details } from '../lib/wall-details'
import './wall-details.css'

/** Shared by the drawing sidebar and the picked 3D wall. */
export function WallDetails({ wall }: { wall: Details }) {
  return <section className="wall-details" aria-label="Wall measurements">
    <p className="wall-detail-status"><strong>{wall.status}</strong> · {wall.classification}</p>
    <dl>
      <div><dt>Length</dt><dd>{wallMeasure(wall.length_m, 'm')}</dd></div>
      <div><dt>Thickness</dt><dd>{wallMeasure(wall.thickness_m, 'm')}</dd></div>
      <div><dt>Height</dt><dd>{wallMeasure(wall.height_m, 'm')} <small>({wall.height_source})</small></dd></div>
      <div><dt>Storey</dt><dd>{wall.storey || 'Not recorded'}</dd></div>
    </dl>
    {wall.faces.map((face) => <div className="wall-detail-face" key={face.label}>
      <h3>{face.label}</h3>
      <dl>
        <div><dt>Gross</dt><dd>{wallMeasure(face.gross_m2, 'm²')}</dd></div>
        <div><dt>Openings deducted</dt><dd>{wall.opening_count === null ? 'Count unavailable' : `${wall.opening_count} opening${wall.opening_count === 1 ? '' : 's'}`} · {wallMeasure(face.opening_m2, 'm²')}</dd></div>
        <div><dt>Net</dt><dd><strong>{wallMeasure(face.net_m2, 'm²')}</strong></dd></div>
      </dl>
    </div>)}
    {(() => { const how = howMeasured(wall); return !!how.length && <details className="wall-detail-how" open>
      <summary>How we measured this</summary>
      <ol>{how.map((line) => <li key={line}>{line}</li>)}</ol>
    </details> })()}
    <p className="wall-detail-method">{wall.method}</p>
    {!!wall.notes.length && <details><summary>Assumptions and limits</summary>{wall.notes.map((note) => <p key={note}>{note}</p>)}</details>}
  </section>
}
