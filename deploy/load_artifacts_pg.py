#!/usr/bin/env python3
"""Store the served files of every listed dataset doc in PostgreSQL (doc_artifacts), so the deployed API can show
a preview, plan map, elements and 3D scene for them (restored lazily per doc by server/artifact_store.ensure_doc).

  python3 deploy/load_artifacts_pg.py --docs-file deployed_docs.json            # dry run: counts and sizes only
  TARGET_DATABASE_URL=... python3 deploy/load_artifacts_pg.py --docs-file ... --apply   # write (resumable)

The docs file is the JSON of GET /api/docs (or a text file with one doc_id per line). Docs need a preview image and
something to answer from (IFC elements, plan map or PDF text); the others are skipped (and stay hidden on the deploy).
Files are staged in a temp dir first: the 3D scene gets the lean USDZ (pipeline/usdz.py) and room/door info
(pipeline/manifest_info.py). Licence rule: CC-BY-ND / GPL docs and scenes with publishable:false are never stored.
Never prints the database URL. Re-running skips docs already stored (--force to overwrite).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
KEEP = re.compile(r"^(scene\.(json|glb|usdz)|elements\.json|doc\.json|pages\.json|planmap-\d+\.json|text(-\d+)?\.json"
                  r"|piping\.json|page-\d+(\.thumb)?\.png)$")


def doc_ids(path: str) -> list[str]:
    txt = Path(path).read_text()
    try:
        j = json.loads(txt)
        return [d["doc_id"] for s in j["sources"] for d in s["docs"] if not d["doc_id"].startswith("uploads__")]
    except ValueError:
        return [x.strip() for x in txt.splitlines() if x.strip()]


def refusal(src: Path) -> str | None:
    def load(p):
        try:
            return json.loads(p.read_text())
        except (OSError, ValueError):
            return {}
    if not (src / "page-1.png").is_file():
        return "no preview image"
    if not ((src / "elements.json").is_file() or any(src.glob("planmap-[0-9]*.json")) or any(src.glob("text*.json"))):
        return "nothing to answer from"
    lic = (load(src / "doc.json").get("licence") or "").upper()
    if lic.startswith(("CC-BY-ND", "GPL")):
        return f"licence {lic}"
    if load(src / "scene.json").get("publishable") is False:
        return "publishable: false"
    return None


def original_of(doc_json: Path) -> Path | None:
    files = json.loads(doc_json.read_text()).get("files") or {}
    roots = [ROOT / "data" / "full" / "junction-dataset", ROOT / "data" / "junction-dataset-preview", ROOT]
    return next((r / rel for rel in files.values() for r in roots if (r / rel).is_file()), None)


def stage(src: Path, dst: Path, lean: bool) -> None:
    dst.mkdir(parents=True)
    for f in src.iterdir():
        if f.is_file() and KEEP.match(f.name):
            shutil.copy2(f, dst / f.name)
    # The original file ("open original") is stored as source.<ext>; docmeta_store.source_file finds it there.
    try:
        orig = original_of(dst / "doc.json")
        if orig is not None:
            shutil.copy2(orig, dst / f"source{orig.suffix.lower()}")
    except Exception as e:  # noqa: BLE001
        print(f"  {dst.name}: original not stored ({repr(e)[:80]})")
    if lean and (dst / "scene.glb").is_file() and (dst / "scene.json").is_file():
        try:
            from pipeline import manifest_info, usdz
            usdz.process(dst.name, dst)
            ifc = None
            try:
                rel = json.loads((dst / "doc.json").read_text()).get("files", {}).get("ifc")
                if rel:
                    ifc = ROOT / rel
                    if not ifc.exists():
                        ifc = ROOT / "data" / "junction-dataset-preview" / rel.removeprefix("data/")
            except Exception:  # noqa: BLE001
                pass
            manifest_info.enrich(dst, ifc)
        except Exception as e:  # noqa: BLE001
            print(f"  {dst.name}: 3D refresh skipped ({repr(e)[:120]})")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs-file", required=True)
    ap.add_argument("--src", default=str(ROOT / "artifacts"))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-lean", action="store_true", help="store scene files as they are")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    baked = {p.name for p in (ROOT / "deploy" / "demo_artifacts").glob("*__*")}  # already in the image
    every = doc_ids(a.docs_file)
    all_ok = [d for d in every if (Path(a.src) / d).is_dir() and not refusal(Path(a.src) / d)]
    ids = [d for d in every if d not in baked]
    ok, skipped, total = [], {}, 0
    for d in ids:
        r = refusal(Path(a.src) / d) if (Path(a.src) / d).is_dir() else "no artifacts"
        if r:
            skipped.setdefault(r, []).append(d)
        else:
            ok.append(d)
    print(f"{len(ids)} listed, {len(ok)} servable, skipped: " + ", ".join(f"{k}: {len(v)}" for k, v in skipped.items()))
    if a.limit:
        ok = ok[:a.limit]
    if not a.apply:
        for d in ok:
            total += sum(f.stat().st_size for f in (Path(a.src) / d).iterdir() if f.is_file() and KEEP.match(f.name))
        print(f"dry run: about {total / 1e6:.0f} MB before lean 3D; nothing written")
        return 0
    url = os.environ.get("TARGET_DATABASE_URL")
    if not url:
        print("set TARGET_DATABASE_URL to the database to write to")
        return 2
    import asyncpg
    from server import artifact_store
    pool = await asyncpg.create_pool(url, min_size=1, max_size=2)
    have = {r["doc_id"] for r in await pool.fetch("select distinct doc_id from doc_artifacts")}
    done = n_bytes = 0
    for d in ok:
        if d in have and not a.force:
            continue
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["ARTIFACTS_DIR"] = tmp
            stage(Path(a.src) / d, Path(tmp) / d, not a.no_lean)
            n_bytes += await artifact_store.save_doc(pool, d, originals=False)
        done += 1
        if done % 25 == 0:
            print(f"  {done} docs, {n_bytes / 1e6:.0f} MB", flush=True)
    # Originals for every listed doc, including baked ones and docs stored before originals were kept.
    have_src = {r["doc_id"] for r in await pool.fetch("select doc_id from doc_artifacts where name like 'source.%'")}
    n_src = src_bytes = 0
    for d in all_ok:
        if d in have_src and not a.force:
            continue
        try:
            orig = original_of(Path(a.src) / d / "doc.json")
        except Exception:  # noqa: BLE001
            orig = None
        if orig is None:
            continue
        data = orig.read_bytes()
        await pool.execute(
            "insert into doc_artifacts (doc_id, name, content_type, data, size) values ($1,$2,$3,$4,$5) "
            "on conflict (doc_id, name) do update set data=excluded.data, size=excluded.size, created_at=now()",
            d, f"source{orig.suffix.lower()}", "application/octet-stream", data, len(data))
        n_src += 1
        src_bytes += len(data)
    print(f"originals stored for {n_src} docs, {src_bytes / 1e6:.0f} MB")
    print(f"stored {done} docs ({len(have & set(ok))} already there), {n_bytes / 1e6:.0f} MB")
    await pool.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
