#!/usr/bin/env python3
"""Copy the publishable artifacts of a few demo docs into deploy/demo_artifacts/ for the image.

  python3 deploy/build_demo_artifacts.py                     # default list (tests/fixtures.json minus the ND doc)
  python3 deploy/build_demo_artifacts.py --docs a b c        # explicit list
  python3 deploy/build_demo_artifacts.py --docs-file list.txt

Refuses docs with `publishable: false` in scene.json or a CC-BY-ND / GPL licence in doc.json.
Copies only the served files (scene.*, elements.json, planmap-*.json, page-N.png + thumb, pages.json,
text-*.json, doc.json) plus, for real version series, series/<id>.json + series/diffs/<id>--i-j.json (PDF revision diffs) and docmeta.json
(folder/discipline/size/date of every shipped doc), never tmp/ or .done-* markers. Prints per-doc and total size (target < 150 MB).
The Dockerfile copies the output to /app/artifacts (ARTIFACTS_DIR).
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "demo_artifacts"
KEEP = re.compile(r"^(scene\.(json|glb|usdz)|elements\.json|doc\.json|pages\.json|planmap-\d+\.json|text-\d+\.json"
                  r"|page-\d+(\.thumb)?\.png)$")
LIMIT_MB = 150
# Real series shipped with the image (opening_design PDFs, CC-BY-SA): 3 sheets issued 3-4 times each.
SERIES = ["vacation-rental--s400-9872c2", "vacation-rental--s401-9b69ee", "vacation-rental--a100-8f1f68"]
DEFAULT = ["ifc_bench__ac20-arc", "ifc_bench__digital-hub-arc",
           "cubicasa5k__colorful-11397", "cubicasa5k__colorful-7513", "cubicasa5k__high-quality-108",
           "cubicasa5k__high-quality-1097",
           "cubicasa5k__high-quality-architectural-10321", "cubicasa5k__high-quality-architectural-12617",
           "swiss_dwellings__site11861-bldg18508-floor50415", "swiss_dwellings__site1869-bldg2903-floor13293",
           "swiss_dwellings__site289-bldg536-floor2149"]


def load(p: Path):
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def refusal(src: Path) -> str | None:
    if not src.is_dir():
        return "no artifacts directory"
    lic = (load(src / "doc.json").get("licence") or "").upper()
    if lic.startswith(("CC-BY-ND", "GPL")):
        return f"licence {lic} is not publishable"
    if load(src / "scene.json").get("publishable") is False:
        return "scene.json says publishable: false"
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", nargs="+")
    ap.add_argument("--docs-file")
    ap.add_argument("--series", nargs="*", default=None, help="series ids to ship (default: SERIES; none: --series)")
    ap.add_argument("--src", default=str(ROOT / "artifacts"))
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    docs = a.docs or ([l.strip() for l in Path(a.docs_file).read_text().splitlines() if l.strip() and not l.startswith("#")]
                      if a.docs_file else DEFAULT)
    src_root, out = Path(a.src), Path(a.out)
    series = []
    for sid in (SERIES if a.series is None else a.series):
        sj = load(src_root / "series" / f"{sid}.json")
        if not sj.get("versions") and a.series is None:
            print(f"skip default series {sid}: not built in {src_root}", file=sys.stderr)
            continue
        if not sj.get("versions"):
            print(f"REFUSED series {sid}: no series file (run python -m pipeline.series --diff)", file=sys.stderr)
            return 1
        series.append(sj)
        docs += [v["doc_id"] for v in sj["versions"] if v["doc_id"] not in docs]
    bad = {d: r for d in docs if (r := refusal(src_root / d))}
    if bad:
        for d, r in bad.items():
            print(f"REFUSED {d}: {r}", file=sys.stderr)
        return 1
    for d in out.iterdir() if out.is_dir() else []:
        if d.is_dir():
            shutil.rmtree(d)
        elif d.name == "docmeta.json":
            d.unlink()
    total = 0
    for d in docs:
        dst = out / d
        dst.mkdir(parents=True, exist_ok=True)
        size = 0
        for f in sorted((src_root / d).iterdir()):
            if f.is_file() and KEEP.match(f.name):
                shutil.copy2(f, dst / f.name)
                size += f.stat().st_size
        total += size
        print(f"{d:<62} {size / 1e6:7.2f} MB")
    meta = load(src_root / "docmeta.json")
    shipped = {k: meta[k] for k in docs if k in meta}
    if shipped:
        (out / "docmeta.json").write_text(json.dumps(shipped, separators=(",", ":")))
    for sj in series:
        (out / "series").mkdir(exist_ok=True)
        (out / "series" / f"{sj['series_id']}.json").write_text(json.dumps(sj, indent=1))
        for f in (src_root / "series" / "diffs").glob(f"{sj['series_id']}--*.json"):
            (out / "series" / "diffs").mkdir(exist_ok=True)
            shutil.copy2(f, out / "series" / "diffs" / f.name)
            total += f.stat().st_size
    mb = total / 1e6
    print(f"TOTAL {len(docs)} docs, {mb:.1f} MB (limit {LIMIT_MB} MB)")
    if mb > LIMIT_MB:
        print("over the size limit", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
