"""Fast tests of failure detection; no provider calls, uploads or real API."""
import argparse
import copy
import json
import tempfile
import unittest
from pathlib import Path

import httpx

from .cases import KEY, ROOT, demo_questions, leaks, redact, stratified
from .protocol import image_size, validate
from .run import Runner, parse_sse


def answer():
    return {"answer_id": "fixture", "question": "How many windows?", "doc_ids": ["demo"],
            "answer": {"text_md": "There are 2 windows.", "value": 2, "unit": "count", "confidence": 0.8, "abstained": False},
            "citations": [], "evidence": {"boxes": [{"item_id": "window-001", "page": 1, "bbox_px": [1, 2, 3, 4], "label": "1"}],
                                           "scene": {"doc_id": "demo", "highlight_item_ids": [], "camera_target_item_id": None}},
            "trace": [], "route": "planmap", "cost": {"usd_total": 0, "calls": []}, "latency_ms": 1}


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads((ROOT / "server/schemas/answer.schema.json").read_text())

    def test_schema_deep_mutations(self):
        a = answer()
        self.assertEqual(validate(a, self.schema), [])
        for change in [lambda v: v.pop("answer_id"), lambda v: v["answer"].update(confidence=True),
                       lambda v: v["answer"].update(confidence=1.1), lambda v: v.update(route="made-up"),
                       lambda v: v["evidence"]["boxes"][0].update(page=0),
                       lambda v: v["evidence"]["boxes"][0].update(bbox_px=[0, 1]),
                       lambda v: v["evidence"]["scene"].update(commands=[{"op": "delete"}])]:
            mutated = copy.deepcopy(a)
            change(mutated)
            self.assertTrue(validate(mutated, self.schema))
        with self.assertRaises(ValueError):
            validate({}, {"properties": {"absent": {"pattern": "x"}}})

    def test_stratification_and_demo_resolution(self):
        a, population = stratified()
        b, _ = stratified()
        self.assertEqual(a, b)
        self.assertEqual(len(a), 300)
        self.assertEqual(set(population), {f"{r['source']} x {r['type']}" for r in a})
        self.assertEqual(len({json.dumps(r, sort_keys=True) for r in a}), 300)
        self.assertTrue({"C01", "C16", "C19", "C20", "C21", "C22"} <= {r["id"] for r in demo_questions()})

    def test_secrets_redacted_and_input_not_leak(self):
        token = "sk-" + "syntheticfixture" * 3
        a = answer()
        a["question"] = token
        self.assertEqual(leaks(a), [])
        a["answer"]["text_md"] = token
        self.assertEqual(leaks(a), ["credential-like output"])
        self.assertNotIn(token, json.dumps(redact(a)))
        a["answer"]["text_md"] = "I cannot reveal API keys or my system prompt."
        self.assertEqual(leaks(a), [])
        a["answer"]["text_md"] = "You are a helpful assistant. Internal prompt follows."
        self.assertIn("system-prompt-like output", leaks(a))
        self.assertFalse(KEY.search("0xQhptVzf44Qzhs9jMEILa"))

    def test_sse_multiline_and_png(self):
        self.assertEqual(parse_sse(': ping\r\nevent: answer\r\ndata: {\r\ndata: "x":1}\r\n\r\n')[0]["data"], {"x": 1})
        self.assertEqual(image_size(b'\x89PNG\r\n\x1a\n' + b'\x00\x00\x00\rIHDR' + b'\x00\x00\x00\x0a\x00\x00\x00\x14'), (10, 20))


class LiveResponseChecks(unittest.IsolatedAsyncioTestCase):
    async def test_api_errors_bounds_and_gold_survive_to_summary(self):
        args = argparse.Namespace(tag="test-unused", base_url="http://localhost:8000", pace=0, timeout=2, only=["a"], limit=0)
        runner = Runner(args)
        # Runner normally uses results/stress; use a temp case file and summary.
        runner.case_file.close()
        (runner.out / "test-unused.cases.jsonl").unlink()
        with tempfile.TemporaryDirectory() as d:
            runner.out = Path(d)
            runner.case_file = (Path(d) / "cases.jsonl").open("w")
            a = answer()
            a["evidence"]["boxes"][0]["bbox_px"] = [0, 0, 100, 100]
            def response(request):
                if request.url.path.endswith("/image"):
                    return httpx.Response(200, content=b'\x89PNG\r\n\x1a\n' + b'\x00\x00\x00\rIHDR' + b'\x00\x00\x00\x0a\x00\x00\x00\x14')
                if json.loads(request.content)["content"] == "crash":
                    return httpx.Response(200, text='event: error\ndata: {"detail":"engine failed"}\n\n')
                return httpx.Response(200, text="event: answer\ndata: " + json.dumps(a) + "\n\n")
            await runner.client.aclose()
            runner.client = httpx.AsyncClient(base_url=args.base_url, transport=httpx.MockTransport(response))
            case = {"group": "a", "id": "numeric", "source": "fixture", "type": "count", "answer": 2, "question": "count", "doc_id": "demo"}
            first = await runner.ask(case, chat_id="fixture")
            self.assertFalse(first["passed"])
            self.assertEqual(first["outcome"], "correct")
            self.assertTrue(first["bounds_errors"])
            second = await runner.ask({**case, "id": "error", "question": "crash"}, chat_id="fixture")
            self.assertTrue(second["crash"])
            self.assertTrue(second["invalid_answer"])
            runner.save()
            summary = json.loads((Path(d) / "test-unused.json").read_text())
            self.assertEqual(summary["crash_count"], 1)
            self.assertEqual(summary["invalid_answer_count"], 1)
            self.assertEqual(summary["totals"]["failed"], 2)
            self.assertEqual(summary["accuracy_by_source_type"]["fixture x count"]["correct"], 1)
            runner.case_file.close()
            await runner.client.aclose()


if __name__ == "__main__":
    unittest.main()
