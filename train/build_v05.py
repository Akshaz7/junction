"""V-05: build the training set (clean CubiCasa5K + FloorPlanCAD + DATA synthetic) with a zero-overlap assert.

  uv run python train/build_v05.py            # writes data/train/v05/{images,labels.jsonl,summary.json}, results/vision/v05_overlap.json
Held-out lists are loaded FRESH from data/sets/ (cubicasa_heldout_ids.txt, heldout_docs.txt) and every training image is also
hash-checked (sha256 + 64-bit dHash, hamming <= 6) against every held-out CubiCasa5K drawing image. No assert, no output.
"""
import hashlib, io, json, random, re, sys, zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import cubicasa_labels as CL
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data/train/v05"
KEEP_FP = {"single_door": "door", "double_door": "door", "sliding_door": "door", "window": "window", "bay_window": "window",
           "toilet": "toilet", "squat_toilet": "toilet", "sink": "sink", "bath_tub": "bathtub"}
FP_MAX = 2000


def dhash(img, n=8):
    g = img.convert("L").resize((n + 1, n))
    px = list(g.getdata())
    bits = 0
    for r in range(n):
        for c in range(n):
            bits = (bits << 1) | (px[r * (n + 1) + c] > px[r * (n + 1) + c + 1])
    return bits


def load_heldout():
    ids = {l.strip() for l in open(ROOT / "data/sets/cubicasa_heldout_ids.txt") if l.strip()}
    docs = {l.strip() for l in open(ROOT / "data/sets/heldout_docs.txt") if l.strip()}
    assert len(ids) >= 4000 and len(docs) >= 4000, "held-out lists look incomplete; refusing to build"
    return ids, docs


def heldout_hashes(docs):
    sh, dh = set(), []
    for d in sorted(docs):
        if not d.startswith("cubicasa5k__"):
            continue
        stem = d.split("__", 1)[1]
        p = None
        for base in ("data/full/junction-dataset/data/cubicasa5k", "data/junction-dataset-preview/data/cubicasa5k"):
            for nm in (stem, stem.replace("high-quality-architectural", "high_quality_architectural").replace("high-quality", "high_quality")):
                q = ROOT / base / (nm + ".png")
                if q.exists():
                    p = q
        if p is None:
            continue
        if True:
            b = p.read_bytes()
            sh.add(hashlib.sha256(b).hexdigest())
            dh.append(dhash(Image.open(io.BytesIO(b))))
    n_cc = sum(1 for d in docs if d.startswith("cubicasa5k__"))
    assert len(sh) >= 0.95 * n_cc, f"only {len(sh)} of {n_cc} held-out images found for hashing"
    return sh, dh


def near(h, dhs, k=6):
    return any(bin(h ^ x).count("1") <= k for x in dhs)


def main():
    rnd = random.Random(5)
    held_ids, held_docs = load_heldout()
    sha_h, dh_h = heldout_hashes(held_docs)
    print("held-out ids", len(held_ids), "docs", len(held_docs), "hashed", len(sha_h), flush=True)
    (OUT / "images").mkdir(parents=True, exist_ok=True)
    recs, report = [], {"dropped": []}

    def add(rec, img):
        b = io.BytesIO(); img.convert("RGB").save(b, "PNG"); raw = b.getvalue()
        sha = hashlib.sha256(raw).hexdigest(); h = dhash(img)
        if sha in sha_h or near(h, dh_h):
            report["dropped"].append(rec["id"]); return
        (OUT / "images" / f"{rec['id']}.png").write_bytes(raw)
        rec["image"] = f"images/{rec['id']}.png"; rec["w"], rec["h"] = img.size; rec["sha256"] = sha
        recs.append(rec)

    # 1) clean CubiCasa5K
    z = zipfile.ZipFile(ROOT / "data/cubicasa5k/cubicasa5k.zip")
    clean = [l.strip() for l in open(ROOT / "data/sets/cubicasa_clean_ids.txt") if l.strip()]
    # the 156 calibration drawings (data/cubicasa5k/calib, used by vision/eval_det.py to pick confidence cuts) stay OUT of training
    calib = {f[:-4].rsplit("_", 1)[0] + "/" + f[:-4].rsplit("_", 1)[1] for f in (p.name for p in (ROOT / "data/cubicasa5k/calib").glob("*.png"))}
    clean = [c for c in clean if c not in calib]
    print("clean cubicasa for training:", len(clean), "(calibration excluded:", len(calib), ")", flush=True)
    for cid in clean:
        assert cid not in held_ids, f"clean id in held-out list: {cid}"
        base = f"cubicasa5k/{cid}/"
        img = Image.open(io.BytesIO(z.read(base + "F1_original.png"))).convert("RGB")
        items = CL.parse(z.read(base + "model.svg").decode(), *img.size)
        add({"id": "cc_" + cid.replace("/", "_"), "source": "cubicasa5k_clean", "origin": cid, "items": items, "has_seg": True}, img)
    # 2) FloorPlanCAD (Voxel51 mirror): boxes only, no wall/room masks
    fp = ROOT / "data/external/fpcad_v51"
    if (fp / "samples.json").exists():
        samples = json.load(open(fp / "samples.json"))["samples"]
        rnd.shuffle(samples)
        n = 0
        for s in samples:
            p = fp / s["filepath"]
            dets = [d for d in (s.get("ground_truth") or {}).get("detections", []) if d["label"] in KEEP_FP]
            if not p.exists() or not dets:
                continue
            img = Image.open(p)
            if img.mode == "RGBA":  # transparent background -> white
                bg = Image.new("RGB", img.size, (255, 255, 255)); bg.paste(img, mask=img.split()[3]); img = bg
            W, H = img.size
            items = [{"kind": KEEP_FP[d["label"]], "bbox_px": [d["bounding_box"][0] * W, d["bounding_box"][1] * H, (d["bounding_box"][0] + d["bounding_box"][2]) * W, (d["bounding_box"][1] + d["bounding_box"][3]) * H], "polygon_px": None} for d in dets]
            add({"id": "fp_" + Path(s["filepath"]).stem, "source": "floorplancad", "origin": s["filepath"], "items": items, "has_seg": False}, img)
            n += 1
            if n >= FP_MAX:
                break
    # 3) DATA synthetic plans
    sy = ROOT / "data/synth"
    for j in sorted(sy.glob("*.json")) if sy.exists() else []:
        png = j.with_suffix(".png")
        if not png.exists():
            continue
        d = json.load(open(j))
        if "items" not in d:
            continue
        add({"id": "sy_" + j.stem, "source": "synthetic", "origin": d.get("doc_id", j.stem), "items": d["items"], "has_seg": True}, Image.open(png))
    # split: val 12% (by drawing, seeded)
    for r in recs:
        r["split"] = "val" if rnd.random() < 0.12 else "train"
    # ---- zero-overlap assert: reload the lists fresh and compare every record
    ids2, docs2 = load_heldout()
    bad = []
    for r in recs:
        o = r["origin"]
        if r["source"] == "cubicasa5k_clean" and (o in ids2 or "cubicasa5k__" + o.replace("_", "-", 1).replace("/", "-") in docs2):
            bad.append(r["id"])
        if r["source"] == "synthetic" and (o in docs2 or o.split("__")[-1] in {x.split("__")[-1] for x in docs2}):
            bad.append(r["id"])
        if r["sha256"] in sha_h:
            bad.append(r["id"])
    assert not bad, f"OVERLAP with held-out: {bad[:10]}"
    with open(OUT / "labels.jsonl", "w") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")
    from collections import Counter
    summ = {"n": len(recs), "by_source": dict(Counter(r["source"] for r in recs)), "by_split": dict(Counter(r["split"] for r in recs)),
            "items_by_kind": dict(Counter(i["kind"] for r in recs for i in r["items"])),
            "heldout_ids": len(ids2), "heldout_docs": len(docs2), "heldout_images_hashed": len(sha_h),
            "overlap": 0, "dropped_by_hash": report["dropped"]}
    json.dump(summ, open(OUT / "summary.json", "w"), indent=1)
    (ROOT / "results/vision").mkdir(parents=True, exist_ok=True)
    json.dump({**summ, "check": "ids (clean list vs cubicasa_heldout_ids), doc ids (heldout_docs), sha256 + dHash(<=6) vs every held-out CubiCasa5K image"}, open(ROOT / "results/vision/v05_overlap.json", "w"), indent=1)
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
