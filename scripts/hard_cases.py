#!/usr/bin/env python3
"""Run conversational hard cases through the web's chat API.

Usage: .venv/bin/python scripts/hard_cases.py [--base http://localhost:8000]
Creates one chat per case. Prints JSONL and saves results/hard_cases/<run>.jsonl.
Expect notes are for human assessment, not automatic grades. API latency_ms is
converted to seconds; missing answers/metrics stay null on failed turns.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from urllib.parse import quote
import uuid

import httpx


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "results/hard_cases.jsonl"
DEFAULT_OUTPUT_DIR = ROOT / "results/hard_cases"


def load_cases(path: Path) -> list[dict]:
    cases, ids = [], set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            case = json.loads(line)
            if not isinstance(case, dict):
                raise ValueError("case must be an object")
            for key in ("id", "doc_id", "question", "expect"):
                if not isinstance(case.get(key), str) or not case[key].strip():
                    raise ValueError(f"{key} must be a nonempty string")
            followups = case.get("followups", [])
            if not isinstance(followups, list) or any(not isinstance(q, str) or not q.strip() for q in followups):
                raise ValueError("followups must be a list of nonempty strings")
            if case["id"] in ids:
                raise ValueError(f"duplicate id: {case['id']}")
        except ValueError as exc:
            raise ValueError(f"{path}:{number}: {exc}") from exc
        ids.add(case["id"])
        cases.append(case)
    if not cases:
        raise ValueError(f"{path}: no cases")
    return cases


def read_answer(lines) -> dict:
    """Read SSE frames, including multiline data and an unterminated last frame."""
    def frames():
        event, data = "message", []
        for line in lines:
            if line == "":
                if data:
                    yield event, "\n".join(data)
                event, data = "message", []
            elif not line.startswith(":"):
                field, _, value = line.partition(":")
                value = value.removeprefix(" ")
                if field == "event":
                    event = value
                elif field == "data":
                    data.append(value)
        if data:
            yield event, "\n".join(data)

    for kind, payload in frames():
        if kind == "error":
            detail = json.loads(payload)
            raise ValueError(f"SSE error: {detail.get('detail', detail) if isinstance(detail, dict) else detail}")
        if kind == "answer":
            value = json.loads(payload)
            if not isinstance(value, dict):
                raise ValueError("SSE answer must be an object")
            return value
    raise ValueError("SSE stream ended without an answer")


def metrics(value: dict) -> dict:
    answer = value["answer"]
    boxes = value["evidence"]["boxes"]
    scene_ids = value["evidence"]["scene"]["highlight_item_ids"]
    cost, latency = value["cost"]["usd_total"], value["latency_ms"]
    if not isinstance(answer["text_md"], str) or not isinstance(answer["abstained"], bool):
        raise ValueError("invalid answer text or abstention flag")
    if not isinstance(boxes, list) or not isinstance(scene_ids, list) or not isinstance(value["route"], str):
        raise ValueError("invalid evidence or route")
    if any(type(n) not in (int, float) or not 0 <= n < float("inf") for n in (cost, latency)):
        raise ValueError("invalid cost or latency")
    return {
        "answer_text": answer["text_md"][:300], "route": value["route"],
        "cost_usd": cost, "latency_s": latency / 1000,
        "evidence_boxes": len(boxes), "scene_ids_count": len(set(scene_ids)),
        "abstained": "yes" if answer["abstained"] else "no",
    }


def run_cases(cases: list[dict], client: httpx.Client, base: str, output: Path) -> bool:
    """Persist/flush each turn immediately; continue after failures without retries."""
    base = base.rstrip("/")
    output.parent.mkdir(parents=True, exist_ok=True)
    failed = False
    with output.open("x", encoding="utf-8") as saved:
        for case in cases:
            chat_id, create_error = None, None
            try:
                response = client.post(f"{base}/api/chats", json={
                    "doc_ids": [case["doc_id"]], "title": f"Hard case: {case['id']}",
                })
                response.raise_for_status()
                chat_id = response.json()["id"]
                if not isinstance(chat_id, str) or not chat_id:
                    raise ValueError("chat response has no id")
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                create_error = f"create chat: {exc}"

            for turn, question in enumerate([case["question"], *case.get("followups", [])], 1):
                row = {
                    "id": case["id"], "doc_id": case["doc_id"], "chat_id": chat_id,
                    "turn": turn, "question": question, "expect": case["expect"],
                    "answer_text": None, "route": None, "cost_usd": None,
                    "latency_s": None, "evidence_boxes": None, "scene_ids_count": None,
                    "abstained": None,
                }
                started = time.perf_counter()
                try:
                    if create_error:
                        raise ValueError(create_error)
                    with client.stream("POST", f"{base}/api/chats/{quote(chat_id, safe='')}/messages",
                                       json={"content": question, "doc_ids": [case["doc_id"]]},
                                       headers={"Accept": "text/event-stream"}) as response:
                        response.raise_for_status()
                        row.update(metrics(read_answer(response.iter_lines())))
                except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                    row["error"] = str(exc)
                    failed = True
                row["elapsed_s"] = time.perf_counter() - started
                line = json.dumps(row, ensure_ascii=False, allow_nan=False)
                saved.write(line + "\n")
                saved.flush()
                print(line, flush=True)
    return not failed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timeout", type=float, default=180, help="HTTP timeout in seconds")
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    try:
        cases = load_cases(args.input)
        run = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex[:8]
        output = args.output_dir / f"{run}.jsonl"
        with httpx.Client(timeout=args.timeout, follow_redirects=True) as client:
            ok = run_cases(cases, client, args.base, output)
        print(f"Saved {output}", file=sys.stderr)
        return 0 if ok else 1
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
