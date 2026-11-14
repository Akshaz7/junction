"""Verified Finnish building rules (accessibility, escape routes) for the advisor.

A rule without a verified URL, section and quote is not allowed to exist.
Validate with: python -m engine.rules.validate
"""
from __future__ import annotations

from pathlib import Path

import yaml

RULES_DIR = Path(__file__).resolve().parent
TRANSLATION_OK = ("official", "source is English")
REQUIRED = ("id", "text", "source_title", "section", "url", "quote", "translation", "check_id")


def load_rules(rules_dir: Path | None = None) -> list[dict]:
    """All rules from engine/rules/*.yaml, each tagged with its file."""
    out: list[dict] = []
    for p in sorted((rules_dir or RULES_DIR).glob("*.yaml")):
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        for r in data.get("rules", []):
            out.append({**r, "file": p.name})
    return out


def translation_valid(value: str) -> bool:
    return value in TRANSLATION_OK or (isinstance(value, str) and value.startswith(("unofficial: our translation", "unofficial: ministry translation")))
