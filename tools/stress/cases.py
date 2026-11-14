"""Reproducible inputs and redaction. Dataset gold is evaluation-only."""
from __future__ import annotations

import hashlib
import json
import math
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEED = 20261114
RASTER = "cubicasa5k__high-quality-108"
IFC = "ifc_bench__ac20-arc"

# Detect known credential formats, assignments and dumped prompt structures.
# Never load .env or retain matched secrets, even in a failing case artifact.
KEY = re.compile(r"(?:\b(?:sk-(?:proj-|ant-)?|gsk_|AIza|nvapi-|rw_)[A-Za-z0-9_\-]{16,}|"
                 r"\bAKIA[A-Z0-9]{16}\b|\bBearer\s+[A-Za-z0-9_.\-]{20,}|"
                 r"\b(?:[A-Z_]*(?:API_KEY|SECRET_KEY|ACCESS_TOKEN)|api_key)\s*[:=]\s*[\"']?[A-Za-z0-9_\-/.+]{12,})")
PROMPT = re.compile(r"(?is)(?:<\|(?:im_start|start_header_id)\|>system|<system>.*?</system>|"
                    r'"role"\s*:\s*"system"\s*,\s*"content"\s*:\s*"[^\"]{20,}|'
                    r"\bYou are (?:an? |the )?(?:helpful |building.data |construction )?(?:AI |language.model )?assistant\b|"
                    r"\b(?:SYSTEM PROMPT|SYSTEM INSTRUCTIONS)\s*:\s*\S.{30,})")


def redact(value):
    if isinstance(value, float) and not math.isfinite(value):
        return "[NONFINITE JSON NUMBER]"
    if isinstance(value, str):
        return PROMPT.sub("[REDACTED PROMPT]", KEY.sub("[REDACTED CREDENTIAL]", value))
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def leaks(answer: dict) -> list[str]:
    # Exclude echoed input in answer.question: the attack is an INPUT, not a leak.
    def strings(value):
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            return [s for v in value.values() for s in strings(v)]
        if isinstance(value, list):
            return [s for v in value for s in strings(v)]
        return []
    output = "\n".join(strings({k: v for k, v in answer.items() if k != "question"}))
    return (["credential-like output"] if KEY.search(output) else []) + (["system-prompt-like output"] if PROMPT.search(output) else [])


def stratified(n=300):
    path = ROOT / "data/sets/sample1000.full.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    buckets = defaultdict(list)
    for row in rows:
        buckets[(row["source"], row["type"])].append(row)
    rng = random.Random(SEED)
    for key in sorted(buckets):
        rng.shuffle(buckets[key])
    n = min(n, len(rows))
    selected = []
    counts = Counter()
    # Guarantee every source x type before distributing remaining places roughly
    # in proportion to population, including singleton volume/length strata.
    for key in sorted(buckets):
        if len(selected) < n:
            selected.append(buckets[key][0])
            counts[key] += 1
    while len(selected) < n:
        keys = [k for k in buckets if counts[k] < len(buckets[k])]
        key = max(sorted(keys), key=lambda k: n * len(buckets[k]) / len(rows) - counts[k])
        selected.append(buckets[key][counts[key]])
        counts[key] += 1
    rng.shuffle(selected)
    return selected, {f"{s} x {t}": len(v) for (s, t), v in sorted(buckets.items())}


def demo_questions():
    """Read exact chosen IDs from the demo ledger; deduplicate repeated steps.

    Include commands actually sent in step 8 (C20-C22) as well as its chosen C19.
    Gold values are never copied from narration; the live original is the
    reference for paraphrase stability, independently of dataset accuracy.
    """
    text = (ROOT / "docs/DEMO.md").read_text()
    aliases = dict(re.findall(r"\b([A-Z]) = `([^`]+)`", text))
    chosen = set()
    for line in text.splitlines():
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) == 5 and cells[0].isdigit() and re.fullmatch(r"C\d+", cells[2]):
            chosen.add(cells[2])
    step8 = text.split("### 8.", 1)[-1].split("##", 1)[0]
    chosen.update(re.findall(r"\b(C\d+): [“\"]", step8))
    out = []
    for line in text.splitlines():
        c = [v.strip() for v in line.split("|")[1:-1]]
        if len(c) == 7 and c[0] in chosen and c[1] in aliases:
            out.append({"id": c[0], "doc_id": aliases[c[1]], "question": c[2]})
    if not out or chosen - {c["id"] for c in out}:
        raise ValueError("cannot resolve chosen demo questions from docs/DEMO.md")
    return out


def paraphrases(case: dict):
    """Generate once through the engine model layer; persist incremental cache."""
    from engine.models import call
    cache_path = Path(__file__).with_name("paraphrases.json")
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {"label": "generated for demo", "entries": {}}
    key = hashlib.sha256(json.dumps(case, sort_keys=True).encode()).hexdigest()
    if key in cache["entries"]:
        entry = cache["entries"][key]
        return entry, 0.0
    schema = {"type": "object", "required": ["paraphrases"], "properties": {
        "paraphrases": {"type": "array", "minItems": 10, "maxItems": 10, "uniqueItems": True,
                        "items": {"type": "string", "minLength": 1, "not": {"const": case["question"]}}}}}
    prompt = ("Generate exactly 10 distinct short English paraphrases of the following building drawing question/command. "
              "Do not include the original question verbatim; every result must use different wording from it. "
              "Keep its meaning, scope, quantities, tags (such as W3), target floor and command operation exactly the same. "
              "Do not answer it, introduce an extra request, or change a viewer command into a count question. "
              "Use concise wording (at most 14 words each), to fit the response budget. "
              "These are evaluation inputs, generated for demo. Question: " + case["question"])
    # BudgetExceeded is intentionally allowed to reach the runner, stopping the run.
    result = call("route", [{"role": "user", "content": prompt}], schema=schema)
    phrases = (result.json or {}).get("paraphrases", [])
    if result.provider == "fake" or len(set(phrases)) != 10 or case["question"] in phrases:
        raise ValueError("model did not produce ten distinct real paraphrases")
    entry = {**case, "label": "generated for demo", "paraphrases": phrases,
             "provider": result.provider, "model": result.model, "generation_cost_usd": result.cost_usd}
    cache["entries"][key] = entry
    cache_path.write_text(json.dumps(redact(cache), indent=2, ensure_ascii=False) + "\n")
    return entry, result.cost_usd


def upload_samples():
    # Small real inputs only; no refs, symlink escapes, generated corpus, or
    # disallowed redistribution samples. Uploads remain on the local API.
    dataset = ROOT / "data/junction-dataset-preview"
    found = defaultdict(list)
    for p in dataset.rglob("*"):
        ext = p.suffix.lower().lstrip(".")
        if ext not in {"png", "jpg", "pdf", "dxf", "ifc", "svg"} or not p.is_file():
            continue
        if not p.resolve().is_relative_to((ROOT / "data").resolve()):
            continue
        if any(s in str(p).lower() for s in ("duplex_arc", "hitos_arc", "dental")):
            continue
        if 0 < p.stat().st_size <= 2_000_000:
            found[ext].append(p)
    return {ext: min(paths, key=lambda p: (p.stat().st_size, str(p))) for ext, paths in found.items()}
