"""F-DESCEVID: evidence trail for descriptive answers ("what is this file", describe, summarise, rooms, title block, notes).

One bounded Claude call (task explain_claims, through engine.models.call) splits the finished answer into claims and
points each at evidence ids that WE supplied (OCR words, plan-map items, title-block fields). Code then validates the
output: unknown ids are dropped, a claim without valid evidence is "inferred", and a claim is only "verified" when its
evidence really exists. The result is reasoning.calc kind "claims" plus confidence factors (schema fixed by the lead).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path

DESCRIPTIVE = re.compile(
    r"\b(what\s+is\s+(this|the)\s+(file|drawing|plan|document|sheet|model|building)|what('?s|\s+is)\s+in\s+(this|the)|describe|summari[sz]e|"
    r"overview|tell\s+me\s+about|which\s+rooms|what\s+rooms|list\s+(the\s+)?rooms|title\s*block|general\s+notes?|notes?\s+on|"
    r"what\s+does\s+(this|the)\s+(drawing|plan|file)\s+(show|contain))\b", re.I)

# Small, sourced-by-us room vocabulary (fi/sv/de/fr/en abbreviations seen in the corpus). Passed to the model and
# used for the check line; the model never invents a translation that is not listed or visible in the words.
ROOM_VOCAB = {
    "kph": "bathroom (fi, kylpyhuone)", "kh": "bathroom (fi, kylpyhuone)", "wc": "toilet", "et": "entrance (fi, eteinen)",
    "oh": "living room (fi, olohuone)", "mh": "bedroom (fi, makuuhuone)", "k": "kitchen (fi, keittio)",
    "kk": "kitchenette (fi, keittokomero)", "tk": "utility/dressing (fi, tyohuone/vaatehuone)", "vh": "wardrobe (fi, vaatehuone)",
    "s": "sauna (fi)", "sauna": "sauna", "parveke": "balcony (fi)", "ranskalainen": "French (fi, of a balcony)",
    "sk": "stairwell (fi, porrashuone)", "var": "storage (fi, varasto)", "ph": "washroom (fi, pesuhuone)",
    "kuisti": "porch (fi)", "keittio": "kitchen (fi)", "olohuone": "living room (fi)", "makuuhuone": "bedroom (fi)",
    "wohnen": "living (de)", "kueche": "kitchen (de)", "küche": "kitchen (de)", "bad": "bathroom (de)", "zimmer": "room (de)",
    "schlafen": "bedroom (de)", "diele": "hall (de)", "flur": "hall (de)", "balkon": "balcony (de)", "cuisine": "kitchen (fr)",
    "chambre": "bedroom (fr)", "salon": "living room (fr)", "sdb": "bathroom (fr)", "kok": "kitchenette (sv, koksnisch)",
}

STATUSES = ("verified", "read_only", "inferred")
SCHEMA = {
    "type": "object", "required": ["claims"], "additionalProperties": False,
    "properties": {"claims": {"type": "array", "items": {
        "type": "object", "required": ["text", "evidence_ids", "status", "check"], "additionalProperties": False,
        "properties": {"text": {"type": "string"}, "evidence_ids": {"type": "array", "items": {"type": "string"}},
                       "status": {"type": "string", "enum": list(STATUSES)}, "check": {"type": "string"}}}}},
}
PROMPT = """You audit a finished answer about a construction drawing. Split the answer into at most 8 factual claims.
For each claim give: text (short), evidence_ids (ONLY ids from the lists below that support it), status, check (one line).
status: "verified" = a listed OCR word / title-block field / plan-map item literally supports it (say which in check, and
use the room vocabulary for translations); "read_only" = supported only by the model's reading of the picture, no listed id;
"inferred" = a conclusion, not directly written on the drawing. Never invent ids or vocabulary. STRICT JSON only:
{{"claims":[{{"text":"","evidence_ids":[""],"status":"verified","check":""}}]}}

ANSWER:
{answer}

OCR WORDS (id: text):
{words}

PLAN-MAP ITEMS (class: count; ids):
{items}

TITLE-BLOCK FIELDS (id: label = value):
{fields}

ROOM VOCABULARY:
{vocab}
"""


def is_descriptive(question: str, res: dict) -> bool:
    ans = res.get("answer") or {}
    if ans.get("abstained") or not (ans.get("text_md") or "").strip():
        return False
    if not DESCRIPTIVE.search(question or ""):
        return False
    if isinstance(ans.get("value"), (int, float)) and not isinstance(ans.get("value"), bool) and ans.get("unit"):
        return False   # numeric answers carry their own calculation
    return True


def _inputs(res: dict, root: Path):
    from engine.solvers.data import load_doc
    doc_id = (res.get("doc_ids") or [""])[0]
    doc = load_doc(doc_id, root) if doc_id else None
    words, wmap = [], {}
    page_n = 1
    try:
        from engine.reader.text import load_page_text
        for page in range(1, min(int(getattr(doc, "pages", 1) or 1), 3) + 1):
            pt = load_page_text(doc_id, page, root, allow_ocr=False)
            for i, w in enumerate(pt.words[:400]):
                t = str(w.get("text") or "").strip()
                if t and w.get("bbox_px"):
                    wid = f"w{page}-{i}"
                    wmap[wid] = {"doc_id": doc_id, "page": page, "item_id": wid, "bbox": w["bbox_px"], "crop": None, "text": t}
                    words.append(f"{wid}: {t}")
            page_n = page
    except Exception:  # noqa: BLE001 - missing text layer just means fewer verifiable claims
        pass
    items, imap, by_kind = [], {}, {}
    for it in (doc.items if doc else []):
        imap[it.item_id] = {"doc_id": doc_id, "page": it.page, "item_id": it.item_id, "bbox": it.bbox_px, "crop": None, "text": it.label or it.name or it.kind}
        by_kind.setdefault(it.kind, []).append(it.item_id)
    for kind, ids in sorted(by_kind.items(), key=lambda kv: -len(kv[1])):
        items.append(f"{kind}: {len(ids)}; ids {', '.join(ids[:6])}{' ...' if len(ids) > 6 else ''}")
    fields, fmap = [], {}
    for k, v in sorted(((doc.meta if doc else None) or {}).items())[:8]:
        if isinstance(v, (str, int, float)) and str(v).strip():
            fid = f"tb-{k}"
            fmap[fid] = {"doc_id": doc_id, "page": 1, "item_id": fid, "bbox": None, "crop": None, "text": f"{k} = {v}"}
            fields.append(f"{fid}: {k} = {str(v)[:80]}")
    if doc and doc.title:
        fmap["tb-title"] = {"doc_id": doc_id, "page": 1, "item_id": "tb-title", "bbox": None, "crop": None, "text": f"title = {doc.title}"}
        fields.append(f"tb-title: title = {doc.title[:80]}")
    return doc, wmap, imap, fmap, by_kind, {"words": words, "items": items, "fields": fields}, page_n


def _vocab_for(words: list[str]) -> dict:
    out = {}
    for line in words:
        t = line.split(": ", 1)[-1].casefold().strip(".,")
        if t in ROOM_VOCAB:
            out[t] = ROOM_VOCAB[t]
    return out


def _fake(answer: str, wmap: dict, imap: dict, fmap: dict) -> dict:
    """Deterministic: one claim per sentence; evidence = ids whose text appears in the sentence, else the first item id."""
    claims = []
    for s in [x.strip() for x in re.split(r"(?<=[.;\n])\s+", answer) if x.strip()][:8]:
        low = s.casefold()
        if not re.sub(r"[\s\[\]\d.,;]", "", s):
            continue
        ev = [i for i, w in {**wmap, **fmap}.items() if len(w["text"]) > 2 and w["text"].casefold() in low][:3]
        kinds = {}
        for i, w in imap.items():
            kinds.setdefault(re.sub(r"-\d+$", "", i), []).append(i)
        for k, ids in kinds.items():
            if re.search(rf"\b{re.escape(k)}s?\b", low) and len(ev) < 3:
                ev.append(ids[0])
        claims.append({"text": s[:160], "evidence_ids": ev, "status": "verified" if ev else "inferred",
                       "check": "fake provider: matched OCR/title text in the sentence" if ev else "fake provider: no matching text"})
    return {"claims": claims}


def validate(raw, wmap, imap, fmap, cite_for_id) -> list[dict]:
    allowed = {**imap, **wmap, **fmap}
    out = []
    for c in (raw.get("claims") if isinstance(raw, dict) else None) or []:
        if not isinstance(c, dict) or not str(c.get("text") or "").strip():
            continue
        ids = [i for i in (c.get("evidence_ids") or []) if isinstance(i, str) and i in allowed]
        status = c.get("status") if c.get("status") in STATUSES else "inferred"
        check = str(c.get("check") or "").strip()[:240]
        if not ids:
            if status == "verified":
                check = (check + " " if check else "") + "No supplied evidence id supports this, downgraded."
            status = "inferred" if status == "verified" else status
            if status == "read_only" and not check:
                check = "Model read of the image only."
        out.append({"text": str(c["text"]).strip()[:240], "ids": ids, "status": status, "check": check or "No check recorded.",
                    "cite": next((cite_for_id[i] for i in ids if i in cite_for_id), None)})
        if len(out) >= 8:
            break
    return out


def _confidence_factors(total, counts, agree):
    share = lambda n: round(100 * n / total) if total else 0  # noqa: E731
    return [
        {"label": "Claims verified by source text", "delta": None, "note": f"{counts['verified']} of {total} claims ({share(counts['verified'])}%) matched OCR words, title-block fields or plan-map items"},
        {"label": "Claims inferred", "delta": None, "note": f"{counts['inferred']} of {total} claims ({share(counts['inferred'])}%) are conclusions, not written on the drawing"},
        {"label": "Model read vs OCR agreement", "delta": None, "note": agree},
    ]


def build(res: dict, question: str, root: Path, on_event=None) -> dict | None:
    from engine.models import call
    doc, wmap, imap, fmap, by_kind, blocks, _ = _inputs(res, root)
    answer = (res.get("answer") or {}).get("text_md") or ""
    if not (wmap or imap or fmap):
        return None
    cite_for_id = {}
    for c in res.get("citations") or []:
        for iid in c.get("item_ids") or []:
            cite_for_id.setdefault(iid, c.get("n"))
    vocab = _vocab_for(blocks["words"])
    prompt = PROMPT.format(answer=answer[:1800], words="; ".join(blocks["words"][:120]) or "(none)",
                           items="\n".join(blocks["items"][:14]) or "(none)", fields="\n".join(blocks["fields"]) or "(none)",
                           vocab="; ".join(f"{k} = {v}" for k, v in vocab.items()) or "(none needed)")
    key = hashlib.sha256((prompt).encode()).hexdigest()[:20]
    cdir = Path(os.environ.get("ARTIFACTS_DIR") or root) / (res.get("doc_ids") or ["_"])[0] / "claims-cache"
    cached = None
    try:
        cached = json.loads((cdir / f"{key}.json").read_text())
    except (OSError, ValueError):
        pass
    model_info = {"provider": "cache", "model": None, "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0}
    if cached is not None:
        raw = cached
    else:
        fake = os.environ.get("MODELS_FAKE", "").strip().lower() in ("1", "true", "yes")
        try:
            r = call("explain_claims", prompt, schema=SCHEMA)
            raw = r.json if isinstance(r.json, dict) else json.loads(r.text)
            if fake or r.provider == "fake":
                raw = _fake(answer, wmap, imap, fmap)
            model_info = {"provider": r.provider, "model": r.model, "cost_usd": r.cost_usd,
                          "input_tokens": r.input_tokens, "output_tokens": r.output_tokens}
        except Exception as e:  # noqa: BLE001 - the answer stands; the trail degrades to a deterministic one
            raw = _fake(answer, wmap, imap, fmap)
            model_info = {"provider": "code", "model": None, "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0, "error": str(e)[:120]}
        if model_info["provider"] not in ("code", "fake"):
            try:
                cdir.mkdir(parents=True, exist_ok=True)
                (cdir / f"{key}.json").write_text(json.dumps(raw))
            except OSError:
                pass
    claims = validate(raw, wmap, imap, fmap, cite_for_id)
    if not claims:
        return None
    allowed = {**imap, **wmap, **fmap}
    counts = Counter(c["status"] for c in claims)
    counts = {s: counts.get(s, 0) for s in STATUSES}
    steps = []
    for c in claims:
        inputs = [{"source": {k: allowed[i][k] for k in ("doc_id", "page", "item_id", "bbox", "crop")}, "text": allowed[i]["text"]} for i in c["ids"][:6]]
        steps.append({"level": "main", "section": "claim", "label": c["text"], "expr": None, "value": None, "unit": None,
                      "status": c["status"], "check": c["check"], "cite": c["cite"], "inputs": inputs})
    inv = ", ".join(f"{k} {len(v)}" for k, v in sorted(by_kind.items(), key=lambda kv: -len(kv[1]))[:12]) or "none"
    steps.append({"level": "detail", "section": "inventory", "label": "Plan-map elements by class", "value": sum(len(v) for v in by_kind.values()), "unit": "elements",
                  "inputs": [], "note": inv})
    sc = (doc.scale if doc else None) or {}
    steps.append({"level": "detail", "section": "scale", "label": "Scale status",
                  "value": sc.get("method") or "not determined", "unit": None, "inputs": []})
    cost = round(model_info["cost_usd"], 6)
    steps.append({"level": "detail", "section": "model_read", "label": "Claim audit model call",
                  "value": f"{model_info['provider']}/{model_info['model'] or 'none'}", "unit": f"{model_info['input_tokens']}+{model_info['output_tokens']} tokens, ${cost}",
                  "inputs": []})
    ocr_hits = sum(1 for c in claims if any(i in wmap for i in c["ids"]))
    agree = (f"{ocr_hits} of {len(claims)} claims cite an OCR word; the model's reading and the OCR text are compared in each claim's check line"
             if wmap else "No OCR/text-layer words were available, so the model read could not be compared with OCR text")
    calc = {"kind": "claims", "formula": None,
            "method": {"id": "read_and_cite", "label": "Read the drawing once, then cite each claim",
                       "why_chosen": "A description is not a number; each statement is split into claims and tied to the words, title-block fields and plan-map items it rests on.",
                       "alternatives": ["Plain model summary without evidence", "Count/measure solvers (not applicable to prose)"]},
            "steps": steps, "checks": [{"method": "OCR / title-block text match", "value": f"{counts['verified']} of {len(claims)}", "agrees": counts["verified"] == len(claims)}],
            "result": {"claims_total": len(claims), "verified": counts["verified"], "read_only": counts["read_only"], "inferred": counts["inferred"]}}
    return {"calc": calc, "factors": _confidence_factors(len(claims), counts, agree), "model": model_info, "counts": counts}


def attach(res: dict, question: str, root: Path, on_event=None) -> dict:
    try:
        if not is_descriptive(question, res):
            return res
        out = build(res, question, root, on_event=on_event)
        if not out:
            return res
        reasoning = res.get("reasoning")
        if not isinstance(reasoning, dict):
            reasoning = res["reasoning"] = {"steps": []}
        reasoning["calc"] = out["calc"]
        conf = reasoning.get("confidence")
        if not isinstance(conf, dict):
            conf = reasoning["confidence"] = {"label": "Estimate", "pct": None}
        conf["factors"] = out["factors"]
        c = out["calc"]["result"]
        conf["reason"] = (f"{c['verified']} of {c['claims_total']} claims verified by source text, {c['read_only']} read only, "
                          f"{c['inferred']} inferred. No measured accuracy is available for descriptive answers.")
        m = out["model"]
        res.setdefault("trace", []).append({"step": "explain_claims", "detail": f"{c['claims_total']} claims audited ({c['verified']} verified)",
                                            "ms": 0, "model": m.get("model"), "cost_usd": m.get("cost_usd", 0.0)})
        cost = res.get("cost")
        if isinstance(cost, dict) and m.get("cost_usd"):
            cost["usd_total"] = round(float(cost.get("usd_total") or 0) + m["cost_usd"], 6)
    except Exception:  # noqa: BLE001 - the audit is a convenience, never break the answer
        pass
    return res
