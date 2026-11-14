"""D-03 question sets. Usage: uv run python -m pipeline.question_sets [--root ...] [--out data/sets]"""
import argparse
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

from pipeline.langcheck import is_english
from pipeline.registry import REPO, doc_id_for_question_path, set_heldout, slug

SEED = 42


def cubicasa_sample_id(path: str) -> str:
    """data/cubicasa5k/colorful-11397.png -> colorful/11397 ; high_quality_architectural-123 -> high_quality_architectural/123"""
    stem = Path(path).stem
    m = re.fullmatch(r"(.+)-(\d+)", stem)
    return f"{m.group(1)}/{m.group(2)}"


def alloc(strata: dict, total: int) -> dict:
    """Proportional allocation (largest remainder), at least 1 per non-empty stratum."""
    n = sum(strata.values())
    out = {k: min(v, max(1, int(total * v / n))) for k, v in strata.items()}
    while sum(out.values()) > total:  # trim the biggest
        k = max(out, key=lambda x: out[x]); out[k] -= 1
    rem = {k: total * strata[k] / n - out[k] for k in strata}
    for k in sorted(rem, key=rem.get, reverse=True):
        if sum(out.values()) >= total:
            break
        if out[k] < strata[k]:
            out[k] += 1
    while sum(out.values()) < total:
        k = next(k for k in sorted(strata, key=strata.get, reverse=True) if out[k] < strata[k])
        out[k] += 1
    return out


def build(root: Path, out: Path, artifacts: Path):
    out.mkdir(parents=True, exist_ok=True)
    qs = [json.loads(l) for l in open(root / "questions.jsonl")]
    for q in qs:
        q["doc_id"] = doc_id_for_question_path(q["path"])
        q["source"] = q["path"].split("/")[1]
    en = [q for q in qs if is_english(q["question"])]
    with open(out / "questions_en.jsonl", "w") as f:
        for q in en:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")

    # held-out: every doc with a question (same-stem siblings share the doc_id) + the IFC model a plan was rendered from
    held = {q["doc_id"] for q in qs}
    for q in qs:
        if q["source"] == "ifc_models" and q["path"].endswith((".pdf", ".svg")):
            stem = Path(q["path"]).stem
            for m in re.finditer(r"_plan-", stem):
                held.add(f"ifc_models__{slug(stem[:m.start()])}")
    (out / "heldout_docs.txt").write_text("\n".join(sorted(held)) + "\n")
    cub = sorted({cubicasa_sample_id(q["path"]) for q in qs if q["source"] == "cubicasa5k"})
    (out / "cubicasa_heldout_ids.txt").write_text("\n".join(cub) + "\n")

    # sample200: stratified by source x type, English only
    rng = random.Random(SEED)
    strata = defaultdict(list)
    for q in en:
        strata[(q["source"], q["type"])].append(q)
    a = alloc({k: len(v) for k, v in strata.items()}, 200)
    sample = []
    for k in sorted(strata):
        pool = sorted(strata[k], key=lambda q: (q["path"], q["question"]))
        sample += rng.sample(pool, a[k])
    sample.sort(key=lambda q: (q["path"], q["question"]))
    with open(out / "sample200.jsonl", "w") as f:
        for q in sample:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")

    # router split 80/20 by drawing (doc_id), stratified by source
    by_src = defaultdict(set)
    for q in en:
        by_src[q["source"]].add(q["doc_id"])
    test_docs = set()
    for s in sorted(by_src):
        docs = sorted(by_src[s]); rng.shuffle(docs)
        test_docs |= set(docs[: max(1, round(0.2 * len(docs)))])
    with open(out / "router_train.jsonl", "w") as ftr, open(out / "router_test.jsonl", "w") as fte:
        for q in en:
            (fte if q["doc_id"] in test_docs else ftr).write(json.dumps(q, ensure_ascii=False) + "\n")

    if (artifacts / "registry.jsonl").exists():
        set_heldout(artifacts, held)
    return len(qs), len(en), len(held)


def _load(root: Path):
    qs = [json.loads(l) for l in open(root / "questions.jsonl")]
    for q in qs:
        q["doc_id"] = doc_id_for_question_path(q["path"])
        q["source"] = q["path"].split("/")[1]
    return qs


def heldout_from(qs) -> set:
    held = {q["doc_id"] for q in qs}
    for q in qs:
        if q["source"] == "ifc_models" and q["path"].endswith((".pdf", ".svg")):
            stem = Path(q["path"]).stem
            for m in re.finditer(r"_plan-", stem):
                held.add(f"ifc_models__{slug(stem[:m.start()])}")
    return held


def cubicasa_all_ids(zip_path: Path) -> set:
    """Official sample ids (colorful/11397) from the directory entries of cubicasa5k.zip."""
    import zipfile
    ids = set()
    with zipfile.ZipFile(zip_path) as z:
        for n in z.namelist():
            m = re.fullmatch(r"cubicasa5k/(colorful|high_quality|high_quality_architectural)/(\d+)/", n)
            if m:
                ids.add(f"{m.group(1)}/{m.group(2)}")
    return ids


def build_full(preview: Path, full: Path, out: Path, artifacts: Path, cub_zip: Path):
    """Held-out lists from the UNION of preview and full questions + full-set English files.
    Does NOT touch sample200 / router_* / questions_en.jsonl (preview-based, kept byte-identical)."""
    qp, qf = _load(preview), _load(full)
    allq = qp + qf
    held = heldout_from(allq)
    (out / "heldout_docs.txt").write_text("\n".join(sorted(held)) + "\n")
    cub = sorted({cubicasa_sample_id(q["path"]) for q in allq if q["source"] == "cubicasa5k"})
    (out / "cubicasa_heldout_ids.txt").write_text("\n".join(cub) + "\n")
    clean = sorted(cubicasa_all_ids(cub_zip) - set(cub)) if cub_zip.exists() else []
    (out / "cubicasa_clean_ids.txt").write_text("\n".join(clean) + "\n")
    en = [q for q in qf if is_english(q["question"])]
    with open(out / "questions_en.full.jsonl", "w") as f:
        for q in en:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")
    rng = random.Random(SEED)
    strata = defaultdict(list)
    for q in en:
        strata[(q["source"], q["type"])].append(q)
    a = alloc({k: len(v) for k, v in strata.items()}, 1000)
    sample = []
    for k in sorted(strata):
        pool = sorted(strata[k], key=lambda q: (q["path"], q["question"]))
        sample += rng.sample(pool, a[k])
    sample.sort(key=lambda q: (q["path"], q["question"]))
    with open(out / "sample1000.full.jsonl", "w") as f:
        for q in sample:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")
    if (artifacts / "registry.jsonl").exists():
        set_heldout(artifacts, held)
    return {"questions_preview": len(qp), "questions_full": len(qf), "english_full": len(en),
            "heldout_docs": len(held), "cubicasa_heldout": len(cub), "cubicasa_clean": len(clean),
            "sample1000": len(sample)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="extend held-out lists to preview + full (D-03b)")
    ap.add_argument("--full-root", default=str(REPO / "data" / "full" / "junction-dataset"))
    ap.add_argument("--cubicasa-zip", default=str(REPO / "data" / "cubicasa5k" / "cubicasa5k.zip"))
    ap.add_argument("--root", default=str(REPO / "data" / "junction-dataset-preview"))
    ap.add_argument("--out", default=str(REPO / "data" / "sets"))
    ap.add_argument("--artifacts", default=str(REPO / "artifacts"))
    a = ap.parse_args()
    if a.full:
        print(json.dumps(build_full(Path(a.root), Path(a.full_root), Path(a.out), Path(a.artifacts),
                                    Path(a.cubicasa_zip))))
    else:
        print(build(Path(a.root), Path(a.out), Path(a.artifacts)))
