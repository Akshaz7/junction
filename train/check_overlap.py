"""V-05: held-out overlap check. Prints `overlap=0` or exits 1.

  .venv/bin/python train/check_overlap.py [labels.jsonl]     # default data/train/v05/labels.jsonl

A training record overlaps if ANY of these hold against ANY drawing referenced by ANY questions.jsonl (preview + full):
  1. origin id / file stem equals a question-referenced doc (CubiCasa id, synthetic source doc id)
  2. sha256 of the training image equals a question-referenced raster image
  3. 64-bit dHash within hamming 6 of a question-referenced raster image
Also fails if a training record is one of the calibration drawings (used to pick confidence cuts).
Writes results/vision/v05_overlap_check.json.
"""
import hashlib, io, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from PIL import Image
from build_v05 import dhash  # noqa: E402  (pure helper, no side effects on import)

ROOT = Path(__file__).resolve().parent.parent
QFILES = [ROOT / "data/junction-dataset-preview/questions.jsonl", ROOT / "data/full/junction-dataset/questions.jsonl"]
BASES = [ROOT / "data/junction-dataset-preview", ROOT / "data/full/junction-dataset", ROOT]


def question_paths():
    ps = set()
    for f in QFILES:
        for l in open(f):
            ps.add(json.loads(l)["path"])
    return ps


def stem_keys(path):
    """Normalised identifiers for a question path: 'colorful-10052', 'colorful/10052', 'high_quality_architectural-1856' ..."""
    s = Path(path).stem
    keys = {s, s.replace("-", "_"), s.replace("_", "-")}
    parts = s.rsplit("-", 1) if "-" in s else s.rsplit("_", 1)
    if len(parts) == 2:
        keys.add(parts[0] + "/" + parts[1])
    return keys


def main():
    labels = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data/train/v05/labels.jsonl"
    recs = [json.loads(l) for l in open(labels)]
    qp = question_paths()
    qkeys = set().union(*(stem_keys(p) for p in qp))
    sha, dh, n_img = set(), [], 0
    for p in qp:
        if not p.lower().endswith(".png"):
            continue
        for b in BASES:
            q = b / p
            if q.exists():
                raw = q.read_bytes(); sha.add(hashlib.sha256(raw).hexdigest()); dh.append(dhash(Image.open(io.BytesIO(raw)))); n_img += 1
                break
    calib = {f.stem for f in (ROOT / "data/cubicasa5k/calib").glob("*.png")}
    bad = []
    for r in recs:
        o = r["origin"]
        keys = {o, Path(o).stem, o.replace("/", "-"), o.replace("/", "_"), r["id"]}
        if r["source"] == "synthetic":
            keys = {o, o.split("__")[-1]}
        if keys & qkeys:
            bad.append((r["id"], "id")); continue
        if r["source"] == "cubicasa5k_clean" and o.replace("/", "_") in calib:
            bad.append((r["id"], "calib")); continue
        img = Image.open(labels.parent / r["image"])
        raw = io.BytesIO(); img.convert("RGB").save(raw, "PNG")
        h = dhash(img)
        if hashlib.sha256(raw.getvalue()).hexdigest() in sha or r.get("sha256") in sha:
            bad.append((r["id"], "sha")); continue
        if any(bin(h ^ x).count("1") <= 6 for x in dh):
            bad.append((r["id"], "dhash"))
    n = len(bad)
    res = {"records": len(recs), "question_docs": len(qp), "question_images_hashed": n_img, "overlap_records": n, "offenders": bad[:20]}
    out = ROOT / "results/vision/v05_overlap_check.json"
    out.write_text(json.dumps(res, indent=1))
    print(f"records={len(recs)} question_docs={len(qp)} question_images_hashed={n_img}")
    print(f"overlap={n}")
    sys.exit(1 if n else 0)


if __name__ == "__main__":
    main()
