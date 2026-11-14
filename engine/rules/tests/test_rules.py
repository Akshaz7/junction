"""Offline tests: rule files are well formed, and the validator catches bad rules.
The live check (real URLs) is `python -m engine.rules.validate`."""
from __future__ import annotations

import io
import zipfile

import pytest

from engine.rules import REQUIRED, load_rules, translation_valid
from engine.rules import validate as v

RULES = load_rules()


def test_library_size_and_unique_ids():
    ids = [r["id"] for r in RULES]
    assert 6 <= len(ids) <= 14
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("r", RULES, ids=lambda r: r["id"])
def test_rule_is_complete(r):
    for k in REQUIRED:
        assert r.get(k), f"{r['id']}: missing {k}"
    assert r["url"].startswith("https://")
    assert translation_valid(r["translation"])
    if r["translation"].startswith("unofficial"):
        assert r.get("quote_en")
    if r.get("finnish_quote"):
        assert r["finnish_url"].startswith("https://www.finlex.fi/")


def test_translation_values():
    assert translation_valid("official") and translation_valid("source is English")
    assert translation_valid("unofficial: our translation")
    assert not translation_valid("unofficial") and not translation_valid("")


def test_normalisation_matches_pdf_and_page_quirks():
    assert v.found("vähintään 1500 millimetriä", "vähintään 1 500   millimetriä")
    assert v.found("vähintään 1500 millimetriä", r"vähintään 1 500 millimetriä")
    assert v.found("riittävästi sopivasti", "riittävästi so- pivasti")
    assert not v.found("vähintään 900 millimetriä", "vähintään 850 millimetriä")


def test_to_text_docx_and_html():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", "<w:p><w:t>Exit width</w:t></w:p><w:p><w:t>1 200</w:t></w:p>")
    assert "Exit width" in v.to_text(buf.getvalue())
    assert "hello" in v.to_text(b"<html><body><p>hello</p></body></html>")


def _rule(**kw):
    base = {"id": "x", "text": "t", "source_title": "s", "section": "1 §", "url": "https://e.test/a",
            "quote": "wide enough", "translation": "source is English", "check_id": "c"}
    return {**base, **kw}


def test_validator_pass_and_fail(monkeypatch):
    monkeypatch.setattr(v, "fetch", lambda url: (200, "A door must be wide   enough here.") if "a" in url else (404, ""))
    assert v.check_rule(_rule())["passed"]
    bad_quote = v.check_rule(_rule(quote="invented sentence"))
    assert not bad_quote["passed"] and "quote not found" in bad_quote["problems"][0]
    dead = v.check_rule(_rule(url="https://e.test/b"))
    assert not dead["passed"] and "404" in dead["problems"][0]


def test_validator_rejects_missing_fields_and_bad_translation(monkeypatch):
    monkeypatch.setattr(v, "fetch", lambda url: (200, "wide enough"))
    r = _rule()
    del r["section"]
    assert not v.check_rule(r)["passed"]
    assert not v.check_rule(_rule(translation="machine"))["passed"]
    assert not v.check_rule(_rule(translation="unofficial: our translation"))["passed"]  # no quote_en
    assert not v.check_rule(_rule(url="http://e.test/a"))["passed"]


def test_finnish_pair_checked_separately(monkeypatch):
    pages = {"https://e.test/en": "wide enough", "https://e.test/fi": "riittävän leveä"}
    monkeypatch.setattr(v, "fetch", lambda url: (200, pages[url]))
    ok = _rule(url="https://e.test/en", finnish_url="https://e.test/fi", finnish_quote="riittävän leveä")
    assert v.check_rule(ok)["passed"]
    bad = _rule(url="https://e.test/en", finnish_url="https://e.test/fi", finnish_quote="ei löydy")
    assert not v.check_rule(bad)["passed"]
