"""Dependency-free calculation audit exports. All rows; no display truncation."""
from __future__ import annotations

import csv
import html
import io
import json


def _calc(res):
    return (res.get("reasoning") or {}).get("calc") or {}


def _cell(value):
    if value is None: return ""
    if isinstance(value, (dict, list)): return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _csv_cell(value):
    text = _cell(value)
    # Prevent spreadsheet evaluation of file-supplied labels/ids.
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) and not isinstance(value, (int, float)) else text


def to_csv(res):
    rows = _calc(res).get("rows", [])
    keys = sorted({k for r in rows for k in r.get("values", {})})
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(["item_id", "label", *keys, "doc_id", "page", "bbox", "artifact", "field", "source"])
    for r in rows:
        src = r.get("source") or {}
        writer.writerow([_csv_cell(v) for v in [r.get("item_id"), r.get("label"), *[r.get("values", {}).get(k) for k in keys],
                                               src.get("doc_id"), src.get("page"), src.get("bbox"), src.get("artifact"), src.get("field"), src]])
    return out.getvalue()


def _md(value):
    return html.escape(_cell(value), quote=False).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ").replace("`", "\\`")


def to_markdown(res):
    calc = _calc(res)
    lines = ["# Calculation report", "", "## Question", "", _md(res.get("question")), "", "## Answer", "",
             _md((res.get("answer") or {}).get("text_md")), "", "## Formula", "", _md(calc.get("formula") or "Calculation not recorded."),
             "", f"Audit status: {_md(calc.get('status') or 'unavailable')}", "", "## Steps and inputs", ""]
    for s in calc.get("steps", []):
        lines.extend([f"### {_md(s.get('label'))} ({_md(s.get('id'))})", "",
                      f"{_md(s.get('expr'))} = {_md(s.get('value'))} {_md(s.get('unit'))}", ""])
        for i in s.get("inputs", []):
            lines.append(f"- {_md(i.get('name'))}: {_md(i.get('value'))} {_md(i.get('unit'))}; source: {_md(i.get('source'))}")
        if s.get("note"): lines.extend(["", _md(s["note"])])
        lines.append("")
    lines.extend(["## Per-element quantities", "", "| Item | Label | Values | Source |", "|---|---|---|---|"])
    lines.extend(f"| {_md(r.get('item_id'))} | {_md(r.get('label'))} | {_md(r.get('values'))} | {_md(r.get('source'))} |" for r in calc.get("rows", []))
    lines.extend(["", "## Result", "", _md(calc.get("result")), "", "## Checks", ""])
    lines.extend(["- " + _md(c) for c in calc.get("checks", [])] or ["No independent check recorded."])
    lines.extend(["", "## Margin", "", _md(calc.get("margin") or "No measured error budget recorded.")])
    missing = list(dict.fromkeys([*(calc.get('issues') or []), *(calc.get('unavailable') or [])]))
    if missing: lines.extend(["", "## Unresolved evidence", "", *["- " + _md(i) for i in missing]])
    return "\n".join(lines) + "\n"


def to_html(res):
    """Standalone, escaped, printable report; no external assets or script."""
    calc = _calc(res)
    esc = lambda v: html.escape(_cell(v), quote=True)
    parts = ["<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>Calculation report</title>",
             "<style>body{font:15px system-ui;margin:2rem;line-height:1.5}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:.4rem;text-align:left;overflow-wrap:anywhere}pre{white-space:pre-wrap}h2,h3{break-after:avoid}tr{break-inside:avoid}</style></head><body>",
             "<h1>Calculation report</h1><h2>Question</h2><p>" + esc(res.get("question")) + "</p><h2>Answer</h2><pre>" + esc((res.get("answer") or {}).get("text_md")) + "</pre>",
             "<h2>Formula</h2><p>" + esc(calc.get("formula") or "Calculation not recorded.") + "</p><p>Audit status: " + esc(calc.get("status") or "unavailable") + "</p><h2>Steps and inputs</h2>"]
    for s in calc.get("steps", []):
        parts.append(f"<h3>{esc(s.get('label'))} ({esc(s.get('id'))})</h3><p>{esc(s.get('expr'))} = {esc(s.get('value'))} {esc(s.get('unit'))}</p><ul>")
        parts.extend(f"<li>{esc(i.get('name'))}: {esc(i.get('value'))} {esc(i.get('unit'))}; source: {esc(i.get('source'))}</li>" for i in s.get("inputs", []))
        parts.append("</ul><p>" + esc(s.get("note")) + "</p>")
    parts.append("<h2>Per-element quantities</h2><table><thead><tr><th>Item</th><th>Label</th><th>Values</th><th>Source</th></tr></thead><tbody>")
    parts.extend("<tr>" + "".join("<td>" + esc(r.get(k)) + "</td>" for k in ("item_id", "label", "values", "source")) + "</tr>" for r in calc.get("rows", []))
    parts.extend(["</tbody></table><h2>Result</h2><pre>" + esc(calc.get("result")) + "</pre><h2>Checks</h2><pre>" + esc(calc.get("checks") or "No independent check recorded.") + "</pre>",
                  "<h2>Margin</h2><pre>" + esc(calc.get("margin") or "No measured error budget recorded.") + "</pre>"])
    missing = list(dict.fromkeys([*(calc.get('issues') or []), *(calc.get('unavailable') or [])]))
    if missing: parts.append("<h2>Unresolved evidence</h2><pre>" + esc(missing) + "</pre>")
    return "".join(parts) + "</body></html>"
