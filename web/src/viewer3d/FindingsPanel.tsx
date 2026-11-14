import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { Viewer } from './viewer';
import { findingColors, type Finding, type FindingSeverity } from './findings';
import { onFindingsUpdated } from './liveHighlight';

function sourceUrl(url?: string | null): string | undefined {
  return url && /^https?:\/\//i.test(url) ? url : undefined;
}

/** Fetch only while enabled; source text is displayed verbatim from the API. */
export function FindingsPanel({ viewer, stage }: { viewer: Viewer | null; stage: HTMLDivElement | null }) {
  const [enabled, setEnabled] = useState(false);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [selected, setSelected] = useState<Finding[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const fetchRef = useRef<(run?: boolean) => Promise<void>>(async () => {});
  const docId = viewer?.scene?.manifest.doc_id;

  useEffect(() => {
    setSelected([]); setFindings([]); setError(''); setStatus(''); setLoading(false);
    if (!enabled || !viewer || !docId) return;
    let active = true;
    let version = 0;
    const controllers = new Set<AbortController>();
    async function refresh(run = false) {
      const current = ++version;
      const controller = new AbortController(); controllers.add(controller);
      setLoading(true); setError('');
      try {
        const response = await fetch(run ? '/api/findings/run' : `/api/findings?doc_id=${encodeURIComponent(docId!)}`, {
          ...(run ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ doc_id: docId }) } : {}),
          signal: controller.signal,
        });
        if (!response.ok) throw new Error(`${run ? 'Checks' : 'Findings'} unavailable (${response.status}).`);
        const data = await response.json() as { findings: Finding[]; status?: string; detail?: string };
        if (!Array.isArray(data.findings)) throw new Error('Findings response is unavailable.');
        if (!active || current !== version) return;
        setFindings(data.findings); setSelected([]);
        setStatus(data.status === 'no_checks' ? data.detail || 'Checks are not available yet.'
          : data.findings.length ? '' : 'No findings returned.');
      } catch (reason) {
        if (active && current === version) setError(reason instanceof Error ? reason.message : 'Findings unavailable.');
      } finally {
        controllers.delete(controller);
        if (active && current === version) setLoading(false);
      }
    }
    fetchRef.current = refresh;
    const stop = onFindingsUpdated((event) => { if (event.doc_id === docId) void refresh(); });
    void refresh();
    return () => {
      active = false; stop(); controllers.forEach((controller) => controller.abort());
      fetchRef.current = async () => {};
    };
  }, [enabled, viewer, docId]);

  useEffect(() => {
    viewer?.setFindings(enabled ? findings : [], setSelected);
    return () => viewer?.setFindings([]);
  }, [viewer, enabled, findings]);

  const card = enabled && selected.length > 0 && <aside className="viewer3d-findings-card" aria-label="Finding details">
    <button type="button" className="viewer3d-findings-close" aria-label="Close findings" onClick={() => setSelected([])}>×</button>
    {selected.map((finding) => <article key={finding.id}>
      <h2>{finding.rule_id}</h2>
      <blockquote>{finding.rule.text}</blockquote>
      {(finding.rule.source_title || finding.rule.section || sourceUrl(finding.rule.url)) && <p className="viewer3d-finding-source">
        {sourceUrl(finding.rule.url)
          ? <a href={sourceUrl(finding.rule.url)} target="_blank" rel="noreferrer">{finding.rule.source_title || finding.rule.url}</a>
          : finding.rule.source_title} {finding.rule.section}
      </p>}
      {finding.message.trim() && <>
        <p>{finding.message}</p>
        <dl>{Object.entries(finding.detail ?? {}).map(([key, value]) => <div key={key}>
          <dt>{key}</dt><dd>{typeof value === 'string' ? value : JSON.stringify(value)}</dd>
        </div>)}</dl>
      </>}
      <button type="button" onClick={() => viewer?.applyCommand({ op: 'highlight', item_ids: finding.item_ids })}>Show items</button>
    </article>)}
  </aside>;

  return <>
    <button type="button" aria-pressed={enabled} disabled={!viewer} onClick={() => setEnabled(!enabled)}>Findings</button>
    {enabled && <>
      <button type="button" disabled={loading || !viewer} onClick={() => void fetchRef.current(true)}>Run checks</button>
      <span className="viewer3d-findings-legend" aria-label="Finding severity legend">
        {(['violation', 'suggestion', 'info'] as FindingSeverity[]).map((severity) =>
          <span key={severity}><i style={{ background: findingColors[severity] }} />{severity}</span>)}
      </span>
      <span className="viewer3d-findings-scope">All storeys</span>
      {loading && <span role="status">Loading findings…</span>}
      {error && <span role="alert">{error}</span>}
      {!loading && status && <span role="status">{status}</span>}
    </>}
    {stage && card && createPortal(card, stage)}
  </>;
}
