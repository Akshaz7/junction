"""F-TABLEOPS: table sums are built from the cited cells; price questions never become order quantities."""
import json

import pytest

from engine import calc, price_intent


def _table_res(value=7, quotes=("4", "3")):
    return {"question": "How many windows are listed?", "answer": {"value": value, "unit": "count", "text_md": f"**{value} windows**", "abstained": False},
            "doc_ids": ["tbl"], "trace": [],
            "citations": [{"doc_id": "tbl", "page": 1, "kind": "text", "item_ids": [], "quote": q, "bbox_px": [10 * i, 5, 10 * i + 8, 15]}
                          for i, q in enumerate(quotes, 1)]}


def _root(tmp_path):
    d = tmp_path / "tbl"
    d.mkdir()
    (d / "text-1.json").write_text(json.dumps({"words": [{"text": "4"}, {"text": "3"}]}))
    return tmp_path


def test_four_plus_three_is_built_from_the_cited_cells(tmp_path):
    r = calc.attach(_table_res(), "How many windows are listed?", _root(tmp_path))
    c = r["reasoning"]["calc"]
    assert c["status"] == "complete"
    assert [x["values"]["count"] for x in c["rows"]] == [4, 3]
    assert "4 + 3" in c["steps"][0]["expr"] and c["steps"][0]["value"] == 7
    assert all(i["source"]["text"] in ("4", "3") for i in c["steps"][0]["inputs"])


def test_cells_that_do_not_sum_to_the_answer_are_not_used(tmp_path):
    r = calc.attach(_table_res(value=8), "How many windows are listed?", _root(tmp_path))
    assert r["reasoning"]["calc"]["status"] == "incomplete"      # no balancing term invented


@pytest.mark.parametrize("q,expect", [
    ("What is the purchase price of the windows? Use only this drawing.", True),
    ("What does it cost to buy the doors?", True),
    ("How much does each window cost?", True),
    ("Order 10% waste for floor tiles, price 35 EUR per m2", False),
    ("How many windows should I order?", False),
    ("What is the cost of this answer?", False),
])
def test_price_intent(q, expect):
    assert price_intent.asks_price(q) is expect


def test_price_question_abstains_without_price_data(tmp_path, monkeypatch):
    from engine.answer import answer
    d = tmp_path / "plan__x"
    d.mkdir()
    (d / "doc.json").write_text(json.dumps({"doc_id": "plan__x", "files": {}}))
    (d / "text-1.json").write_text(json.dumps({"words": [{"text": "KITCHEN"}]}))
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("MODELS_FAKE", "1")
    monkeypatch.setenv("ANSWER_TIMEOUT_S", "0")
    r = answer("What is the purchase price of the windows?", ["plan__x"])
    assert r["answer"]["abstained"] and "no price in the drawings" in r["answer"]["text_md"].lower()
    assert "Order" not in r["answer"]["text_md"]


def test_price_data_in_document_lets_the_question_through(tmp_path):
    d = tmp_path / "reg"
    d.mkdir()
    (d / "text-1.json").write_text(json.dumps({"words": [{"text": "Unit"}, {"text": "price"}, {"text": "125"}]}))
    assert price_intent.doc_has_price_data("reg", tmp_path)
