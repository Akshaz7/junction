"""Validate every rule: URL returns 200 and the quote is in the fetched text.

    python -m engine.rules.validate [--offline-cache DIR] [--out results/rules_validation.json]

HTML, PDF (pdfminer.six) and DOCX (zip, word/document.xml) sources are supported. Whitespace,
no-break spaces and PDF line-end hyphenation are normalised before matching.
"""
from __future__ import annotations

import argparse
import html
import io
import json
import re
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

from . import REQUIRED, load_rules, translation_valid

ROOT = Path(__file__).resolve().parents[2]
UA = "rules-validator/1.0"


def norm(s: str) -> str:
    s = html.unescape(s).replace(" ", " ").replace(" ", " ").replace(" ", " ")
    s = s.replace("­", "").replace("‑", "-")
    s = re.sub(r"\\u(00a0|2009|202f)", " ", s, flags=re.I)  # escaped spaces inside embedded page data
    s = re.sub(r"(?<=\d) (?=\d{3}\b)", "", s)  # digit grouping: "1 500" == "1500"
    return re.sub(r"\s+", " ", s).strip()


def variants(text: str) -> list[str]:
    """Two readings of the same text: as is, and with line-end hyphenation joined (PDFs)."""
    a = norm(text)
    b = re.sub(r"(?<=[a-zäöå])- (?=[a-zäöå])", "", a)
    return [a, b]


def to_text(data: bytes) -> str:
    if data[:4] == b"%PDF":
        from pdfminer.high_level import extract_text
        return extract_text(io.BytesIO(data))
    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
        xml = re.sub(r"</w:p>", "\n", xml)
        return re.sub(r"<[^>]+>", "", xml)
    t = data.decode("utf-8", "replace")
    # Finlex is a Next.js app: statute text sits in the page's embedded data, so scripts are kept.
    return re.sub(r"(?s)<(?!/?script)[^>]+>", " ", t)


_cache: dict[str, tuple[int, str]] = {}


def fetch(url: str) -> tuple[int, str]:
    if url in _cache:
        return _cache[url]
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            code, data = r.status, r.read()
    except urllib.error.HTTPError as e:
        code, data = e.code, b""
    except Exception as e:  # network down, DNS, timeout
        _cache[url] = (0, f"{type(e).__name__}: {e}")
        return _cache[url]
    try:
        text = to_text(data) if code == 200 else ""
    except Exception as e:
        text = ""
        code = -1
    _cache[url] = (code, text)
    return _cache[url]


def found(quote: str, text: str) -> bool:
    q = norm(quote)
    return any(q in v for v in variants(text))


def check_pair(url: str, quote: str) -> dict:
    code, text = fetch(url)
    return {"url": url, "http_status": code, "url_ok": code == 200,
            "quote_found": code == 200 and found(quote, text)}


def check_rule(r: dict) -> dict:
    problems = [f"missing {k}" for k in REQUIRED if not r.get(k)]
    if r.get("translation") and not translation_valid(r["translation"]):
        problems.append(f"bad translation value {r['translation']!r}")
    if str(r.get("translation", "")).startswith("unofficial") and not r.get("quote_en"):
        problems.append("unofficial translation needs quote_en")
    if not str(r.get("url", "")).startswith("https://"):
        problems.append("url must be https")
    res = {"id": r.get("id"), "file": r.get("file"), "section": r.get("section"),
           "check_id": r.get("check_id"), "translation": r.get("translation"), "sources": []}
    if not problems:
        res["sources"].append({"role": "quote", **check_pair(r["url"], r["quote"])})
        if r.get("finnish_url") or r.get("finnish_quote"):
            if not (r.get("finnish_url") and r.get("finnish_quote")):
                problems.append("finnish_url and finnish_quote go together")
            else:
                res["sources"].append({"role": "finnish_quote", **check_pair(r["finnish_url"], r["finnish_quote"])})
    for s in res["sources"]:
        if not s["url_ok"]:
            problems.append(f"{s['role']}: url returned {s['http_status']}")
        elif not s["quote_found"]:
            problems.append(f"{s['role']}: quote not found in page text")
    res["problems"] = problems
    res["passed"] = not problems
    return res


def run() -> dict:
    rules = load_rules()
    ids = [r.get("id") for r in rules]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    results = [check_rule(r) for r in rules]
    passed = all(x["passed"] for x in results) and bool(results) and not dup
    return {"checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "rules": len(results),
            "passed": passed, "duplicate_ids": dup, "results": results}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "results" / "rules_validation.json"))
    a = ap.parse_args(argv)
    rep = run()
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for x in rep["results"]:
        print(("PASS " if x["passed"] else "FAIL ") + f"{x['id']} ({x['section']})" +
              ("" if x["passed"] else "  " + "; ".join(x["problems"])))
    print(f"{sum(x['passed'] for x in rep['results'])}/{rep['rules']} rules passed -> {out}")
    return 0 if rep["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
