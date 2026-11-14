#!/usr/bin/env python3
"""Tidy .env without ever printing a value.

Fixes: `export KEY=v`, `KEY: v`, `KEY = v`, quotes (incl. TextEdit curly quotes),
trailing spaces, Windows line endings, duplicate keys (last non-empty wins), and bare
pasted values on their own line when the key type is recognisable by prefix.
Unknown names are kept. Order follows .env.example. Writes a backup to .env.bak.
Prints only key names and what was done.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV, EXAMPLE = ROOT / ".env", ROOT / ".env.example"

# Prefix -> key name, for values pasted without a name.
PREFIXES = [
    (r"^sk-ant-", "ANTHROPIC_API_KEY"),
    (r"^AIza", "GEMINI_API_KEY"),
    (r"^nvapi-", "NVIDIA_API_KEY"),
    (r"^hf_", "HF_TOKEN"),
    (r"^cloudinary://", "CLOUDINARY_URL"),
    (r"^postgres(ql)?://", "DATABASE_URL"),
    (r"^ak-[A-Za-z0-9]", "MODAL_TOKEN_ID"),
    (r"^as-[A-Za-z0-9]", "MODAL_TOKEN_SECRET"),
    (r"^sk_[0-9a-f]{40,}$", "ELEVENLABS_API_KEY"),
]
QUOTES = "\"'“”‘’`"


def clean(v: str) -> str:
    v = v.strip().strip(QUOTES).strip()
    return v.replace(" ", "").replace("​", "")


def main() -> None:
    order = [l.split("=", 1)[0].strip() for l in EXAMPLE.read_text().splitlines()
             if "=" in l and not l.lstrip().startswith("#")]
    raw = ENV.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    vals: dict[str, str] = {}
    notes: list[str] = []
    unknown_bare = 0
    for line in raw.split("\n"):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        s = re.sub(r"^export\s+", "", s)
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*[:=]\s*(.*)$", s)
        if m:
            k, v = m.group(1).upper(), clean(m.group(2))
            if v:
                if k in vals and vals[k] != v:
                    notes.append(f"{k}: duplicate, kept the later value")
                vals[k] = v
            else:
                vals.setdefault(k, "")
            continue
        v = clean(s)
        for pat, k in PREFIXES:
            if re.match(pat, v):
                if not vals.get(k):
                    vals[k] = v
                    notes.append(f"{k}: bare pasted value recognised and named")
                break
        else:
            unknown_bare += 1
    shutil.copy2(ENV, ENV.with_suffix(".bak"))
    keys = order + [k for k in vals if k not in order]
    out = ["# Keys for the Junction build. Never commit this file."]
    out += [f"{k}={vals.get(k, '')}" for k in keys]
    ENV.write_text("\n".join(out) + "\n")
    for n in notes:
        print(n)
    if unknown_bare:
        print(f"{unknown_bare} line(s) with no name and an unrecognised format were dropped "
              "(still in .env.bak): add NAME= in front of them")
    extra = [k for k in vals if k not in order]
    if extra:
        print("kept extra names:", ", ".join(extra))
    print("filled:", ", ".join(k for k in keys if vals.get(k)) or "none")


if __name__ == "__main__":
    main()
