"""How-to questions about the app itself ("how do I upload files?", "where is Findings?", "can I use voice?", "what can you do?").

app_help_answer(question, doc_ids) -> answer object | None
Grounded ONLY in engine/app_guide.md (written from the real UI labels). Order: keyword match in code ($0) -> Haiku with only the guide
as context -> "the guide does not cover that, see Help". It never invents a button: the model is told to answer from the guide or say NOT_IN_GUIDE.
Document questions ("Where is the stair core on level 2?") are left alone: a how-to phrase must also name an app feature.
"""
from __future__ import annotations

import re
import time
import uuid
from pathlib import Path

GUIDE = Path(__file__).with_name("app_guide.md")
HELP_LINE = "The guide does not cover that. Open **More, then Help** in the app for the written guide."

_PHRASE = re.compile(r"\b(how (?:do|can|could|would|should) (?:i|we|you)|how to|how does|where (?:is|are|do i|can i|would i|to)|can (?:i|we|you)|could (?:i|we)|is there a way|what can (?:you|i|this)|what (?:does|do) (?:the|this)|what is (?:the|a)|help me (?:with|use))\b", re.I)
_WHAT_CAN = re.compile(r"\bwhat can (?:you|i|this app|stoa)\b.*\b(?:do|use)\b|\bwhat (?:are )?(?:your|the app'?s?) (?:features|capabilities)\b|\bwhat does (?:this|the) app do\b", re.I)

# section title -> words that point at it (lower case, matched as whole words / prefixes)
_KEYS: dict[str, list[str]] = {
    "Upload": ["upload", "uploading", "import", "add a file", "add file", "add a drawing", "add drawings", "add a document", "files", "file format", "formats", "pdf", "dxf", "ifc", "png", "jpg"],
    "Ask about a document": ["@", "mention", "mentions", "ask about", "ask a question", "ask questions", "select a document", "choose a document", "include a document", "composer"],
    "Voice": ["voice", "microphone", "mic", "speak", "speech", "dictate"],
    "Citations, sources and the 2D viewer": ["citation", "citations", "source", "sources", "2d", "viewer", "boxes", "zoom", "pan", "drawing viewer", "trace", "thought process", "download original"],
    "Visualise it (3D)": ["visualise", "visualize", "3d", "build slider", "slider", "storey", "storeys", "floor", "walk", "walk through", "roof", "edit items", "undo", "move"],
    "Edits from chat": ["remove", "hide", "restore", "put it back", "delete", "isolate"],
    "Findings and Run checks": ["finding", "findings", "run checks", "checks", "rules", "violation", "compliance", "tools"],
    "Pair a phone": ["pair", "phone", "iphone", "qr", "qr code", "scan", "continue on", "another device", "mobile"],
    "Show on table (AR)": ["ar", "augmented", "show on table", "table", "1:1", "life size", "lifesize"],
    "Export report": ["export", "report", "markdown", "download report"],
    "Share": ["share", "history", "new chat", "chat history", "earlier chat", "previous chat", "old chat", "start a new chat"],
    "Overview": ["overview", "home", "home page", "dashboard"],
    "Changes": ["changes", "what changed", "change feed"],
    "Compare": ["compare", "comparison", "versions", "revisions", "diff"],
    "Library: Skills and Automations": ["library", "skill", "skills", "automation", "automations", "schedule", "scheduled", "recurring"],
    "Data": ["data", "documents", "folders", "folder", "document list", "status", "ready"],
    "Help": ["help", "guide", "manual", "docs"],
    "Navigation": ["navigate", "navigation", "sidebar", "menu", "more menu", "where is", "where are", "find the", "pages", "login", "log in", "account", "sign in", "stoa pro"],
}
_APP_WORDS = re.compile(r"\b(app|stoa|button|screen|page|tab|menu|sidebar|feature|features|upload\w*|import|pair\w*|phone|iphone|qr|voice|microphone|visuali[sz]e|3d|walk\w*|findings?|run checks|checks?|rule checks|export|report|share|history|new chat|compare|changes|library|skills?|automations?|overview|help|citations?|viewer|mention\w*|@|ar|table|storeys?|slider|undo|data|tools|documents?|files?)\b", re.I)
_NOT_APP = re.compile(r"\b(how many|how much|what is the (?:area|length|height|width|volume|total|fire rating|net|gross)|where is the (?:stair|lift|elevator|room|door|window|toilet|kitchen|exit|entrance|bathroom|wc|corridor)|can i (?:fit|park|put)|how (?:do|does) (?:the|this) (?:wall|roof|building|floor|stair|room|door|window)s? )", re.I)


def _guide() -> dict[str, str]:
    out, cur, buf = {}, None, []
    for line in GUIDE.read_text().splitlines():
        if line.startswith("## "):
            if cur:
                out[cur] = "\n".join(buf).strip()
            cur, buf = line[3:].strip(), []
        elif cur:
            buf.append(line)
    if cur:
        out[cur] = "\n".join(buf).strip()
    return out


def is_app_question(q: str) -> bool:
    q = (q or "").strip()
    if not q or len(q) > 300 or _NOT_APP.search(q):
        return False
    if _WHAT_CAN.search(q):
        return True
    return bool(_PHRASE.search(q)) and bool(_APP_WORDS.search(q))


def _has(q: str, key: str) -> bool:
    if key == "@":
        return "@" in q
    return re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", q) is not None


def match_sections(q: str) -> list[str]:
    ql = q.lower()
    scores = {}
    for title, keys in _KEYS.items():
        s = sum(len(k.split()) + (1 if " " in k else 0) for k in keys if _has(ql, k))
        if s:
            scores[title] = s
    # generic words ("where is", "data", "ready", "floor", "move") must not beat a specific hit
    for generic in ("Navigation", "Data", "Help"):
        if len(scores) > 1 and generic in scores:
            scores[generic] = 0
    ranked = [t for t, s in sorted(scores.items(), key=lambda kv: -kv[1]) if s > 0]
    if not ranked:
        return []
    top = scores[ranked[0]]
    return [t for t in ranked[:2] if scores[t] >= max(1, top - 1)][: (2 if top <= 2 else 1)]


def _summary(sections: dict[str, str]) -> str:
    return ("Stoa Pro answers questions about your drawings and models, and every answer shows proof. You can: **upload** PDF, PNG, JPG, DXF or IFC files (Data, then Upload); "
            "**ask** questions in Chat and use @ to pick a document; open **citations** on the 2D drawing; use **Visualise it** for 3D (build slider, storeys, Walk, Edit); "
            "run rule checks under **Tools** (Findings, Run checks); **pair a phone** with the QR code and use **Show on table** for AR in the iPhone app; "
            "**Export report**, **Share**, reopen chats from **History**; and use **Overview**, **Changes**, **Compare** and **Library** (Skills, Automations). Ask me how to do any of these.")


def _model_answer(question: str, guide_text: str, calls: list) -> str | None:
    from engine.models import call
    prompt = ("You answer how-to questions about the Stoa Pro app using ONLY the guide below. Use the exact button and menu names from the guide. "
              "Never mention a button, menu, setting or feature that is not in the guide. If the guide does not answer the question, reply with exactly NOT_IN_GUIDE. "
              "Answer in at most 4 short sentences.\n\n=== GUIDE ===\n" + guide_text + "\n=== END GUIDE ===\n\nQuestion: " + question)
    r = call("app_help", [{"role": "user", "content": prompt}])
    calls.append({"task": "app_help", "provider": r.provider, "model": r.model, "cost_usd": r.cost_usd})
    t = (r.text or "").strip() if hasattr(r, "text") else ""
    if not t or "NOT_IN_GUIDE" in t or r.provider == "fake":
        return None
    return t


def app_help_answer(question: str, doc_ids: list[str]) -> dict | None:
    if not is_app_question(question):
        return None
    t0 = time.perf_counter()
    sections = _guide()
    calls: list = []
    how = "keyword match in the app guide, no model"
    if _WHAT_CAN.search(question) and not match_sections(question):
        text = _summary(sections)
    else:
        hit = match_sections(question)
        if hit:
            text = "\n\n".join(f"**{t}.** {sections[t]}" for t in hit)
        else:
            text, how = None, "no keyword hit: Haiku with only the app guide as context"
            try:
                text = _model_answer(question, "\n\n".join(f"## {t}\n{b}" for t, b in sections.items()), calls)
            except Exception:  # noqa: BLE001
                text = None
            if text is None:
                text, how = HELP_LINE, "the app guide does not cover it: pointed to Help"
    usd = sum(c["cost_usd"] or 0 for c in calls)
    return {
        "answer_id": uuid.uuid4().hex, "question": question, "doc_ids": list(doc_ids),
        "answer": {"text_md": text, "value": None, "unit": None, "confidence": 1.0 if "keyword" in how else 0.8, "abstained": False},
        "citations": [], "evidence": {"boxes": [], "scene": {"doc_id": "", "highlight_item_ids": [], "camera_target_item_id": None}},
        "trace": [{"step": "app_help", "detail": how, "ms": int((time.perf_counter() - t0) * 1000), "model": calls[0]["model"] if calls else None, "cost_usd": usd}],
        "route": "index", "cost": {"usd_total": usd, "calls": calls}, "latency_ms": int((time.perf_counter() - t0) * 1000),
    }
