import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { Viewer } from './viewer';
import { findingColors, type Finding, type FindingSeverity } from './findings';
import { onFindingsUpdated } from './liveHighlight';

/** http(s) URLs only; anything else is not rendered as a link. */
export function sourceUrl(url?: string | null): string | undefined {
  return url && /^https?:\/\//i.test(url) ? url : undefined;
}

export interface FindingsRunResponse {
  findings: Finding[]; status?: string; detail?: string; checked?: string[]; items_checked?: number | null;
  checked_at?: string; edited?: boolean; hidden?: number;
}

function plural(n: number, word: string): string { return `${n} ${word}${n === 1 ? '' : 's'}`; }

/** One honest status line: what was checked, on what, when, and what came out. */
export function findingsStatus(data: FindingsRunResponse, run: boolean): string {
  if (data.status === 'no_checks') return data.detail || 'Checks are not available yet.';
  if (!run) return data.findings.length ? '' : 'No saved findings. Press Run checks to check this drawing.';
  const time = data.checked_at ? new Date(data.checked_at) : null;
  const at = time && !Number.isNaN(time.getTime()) ? ` at ${time.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}` : '';
  const rules = data.checked ? plural(data.checked.length, 'rule') : 'the rules';
  const items = typeof data.items_checked === 'number' ? ` on ${plural(data.items_checked, 'item')}` : '';
  const edits = data.edited && data.hidden ? ` (your ${plural(data.hidden, 'unsaved removal')} applied)` : '';
  const outcome = data.findings.length ? `${plural(data.findings.length, 'finding')}.` : 'no rule problems found.';
  return `Checked ${rules}${items}${edits}${at}: ${outcome}`;
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
        // Unsaved removals from Edit mode go along, so the checks see the drawing as it is on screen.
        const hidden = run ? viewer?.getCommandState().hidden ?? [] : [];
        const response = await fetch(run ? '/api/findings/run' : `/api/findings?doc_id=${encodeURIComponent(docId!)}`, {
          ...(run ? { method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ doc_id: docId, hidden_item_ids: hidden }) } : {}),
          signal: controller.signal,
        });
        if (!response.ok) throw new Error(`${run ? 'Checks' : 'Findings'} unavailable (${response.status}).`);
        const data = await response.json() as FindingsRunResponse;
        if (!Array.isArray(data.findings)) throw new Error('Findings response is unavailable.');
        if (!active || current !== version) return;
        setFindings(data.findings); setSelected([]);
        setStatus(findingsStatus(data, run));
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
      <button type="button" disabled={loading || !viewer} onClick={() => void fetchRef.current(true)}>{loading ? 'Checking…' : 'Run checks'}</button>
      {findings.length > 0 && <span className="viewer3d-findings-legend" aria-label="Finding severity legend">
        {(['violation', 'suggestion', 'info'] as FindingSeverity[]).filter((severity) => findings.some((f) => f.severity === severity)).map((severity) =>
          <span key={severity}><i style={{ background: findingColors[severity] }} />{severity}</span>)}
      </span>}
      <span className="viewer3d-findings-scope">All storeys</span>
      {loading && <span role="status">Checking the drawing…</span>}
      {error && <span role="alert">{error}</span>}
      {!loading && !error && status && <span role="status">{status}</span>}
    </>}
    {stage && card && createPortal(card, stage)}
  </>;
}
