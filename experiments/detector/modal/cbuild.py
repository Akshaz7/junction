"""CLEAN detector training set (no question-referenced Swiss drawing anywhere in train/val) on Modal.
LOCAL ONLY: nothing pushed until Awais verifies it.

    modal.sh run cbuild.py::main [--n-floors 4500] [--limit-shards N]
    modal.sh run cbuild.py::samples         # 2 annotated tiles -> det/clean_samples/

Source: Swiss Dwellings v3.0.0 geometry (CC BY 4.0, Zenodo 7788422), the zip 5b-learn already put on volume junction-roles.
Drawn by crender.py (5b-learn's renderer + per-object instance boxes), rasterised at 40 px per metre, 1280 px tiles
(stride 1024), classes 0 door / 1 window / 2 fixture (features + stairs, like the Swiss DXF FIXTURE layer).
Exclusions (asserted in prep AND in every render shard): union of every site, building and floor named by a
swiss_dwellings path in the FULL /full/junction-dataset/questions.jsonl, the preview list excluded_swiss.json, and
data/sets/heldout_docs.txt if it exists (it does not in this checkout or on the volume).
Split by building: val = crc32(building) % 100 < 8. TEST = all 1,040 dataset Swiss pages with exact DXF labels
(copied from /yolo, prefixed ds_<split>_), unseen by this model.
"""
import json
import os

import modal

app = modal.App("junction-det-clean-build")
vol_r = modal.Volume.from_name("junction-roles")
vol = modal.Volume.from_name("junction-ds")
image = (modal.Image.debian_slim(python_version="3.12")
         .pip_install("numpy==2.1.3", "shapely==2.0.6", "pypdfium2==4.30.0", "pillow==11.0.0", "ezdxf==1.3.4")
         .add_local_python_source("crender", "swisslab"))
EXCL_PREVIEW = json.load(open(os.environ.get("EXCLUDED_SWISS_JSON", "excluded_swiss.json"))) \
    if modal.is_local() else {}
OUT = "/ds/yolo_clean"
SHARD = 40


def _excl_sets(preview):
    """Union of the full questions.jsonl Swiss IDs, the preview list and heldout_docs.txt (if present)."""
    import os, re
    rx = re.compile(r"site(\d+)_bldg(\d+)_floor(\d+)")
    S, B, F = set(preview.get("sites", [])), set(preview.get("buildings", [])), set(preview.get("floors", []))
    n = 0
    for line in open("/ds/full/junction-dataset/questions.jsonl"):
        for m in rx.finditer(line):
            s_, b_, f_ = (int(x) for x in m.groups()); S.add(s_); B.add(b_); F.add(f_); n += 1
    hd = "/ds/sets/heldout_docs.txt"
    hd_present = os.path.exists(hd)
    if hd_present:
        for line in open(hd):
            for m in rx.finditer(line):
                s_, b_, f_ = (int(x) for x in m.groups()); S.add(s_); B.add(b_); F.add(f_)
    return S, B, F, {"question_refs": n, "heldout_docs_txt_present": hd_present}


@app.function(image=image, cpu=2, memory=16384, timeout=1800, volumes={"/v": vol_r, "/ds": vol})
def prep(preview: dict, n_floors: int = 4500, frac: int = 3) -> dict:
    import csv, hashlib, io, os, shutil, sys, zipfile, zlib
    csv.field_size_limit(sys.maxsize)
    S, B, F, info = _excl_sets(preview)
    z = "/v/swiss-dwellings-v3.0.0.zip"
    assert os.path.exists(z), "Swiss v3 zip missing on junction-roles"
    floors, meta, n_rows, n_ex = {}, {}, 0, 0
    with zipfile.ZipFile(z) as zf:
        with zf.open("swiss-dwellings-v3.0.0/geometries.csv") as fh:
            for r in csv.DictReader(io.TextIOWrapper(fh, "utf-8")):
                n_rows += 1
                s, b, f = int(r["site_id"]), int(float(r["building_id"])), int(float(r["floor_id"]))
                if s in S or b in B or f in F:
                    n_ex += 1; continue
                if int(hashlib.md5(f"det{f}".encode()).hexdigest(), 16) % frac:
                    continue
                if r["entity_subtype"] == "NOT_DEFINED":
                    continue
                floors.setdefault(f, []).append({"entity_type": r["entity_type"], "entity_subtype": r["entity_subtype"],
                                                 "geometry": r["geometry"]})
                meta[f] = (s, b)
    ids = sorted(floors)[:n_floors]
    ov = ({meta[f][0] for f in ids} & S, {meta[f][1] for f in ids} & B, set(ids) & F)
    assert not any(ov), f"HELD-OUT OVERLAP {ov}"
    shutil.rmtree("/ds/clean_shards", ignore_errors=True); os.makedirs("/ds/clean_shards")
    for sp_ in ("train", "val"):  # never mix tiles of an earlier selection
        for kd in ("images", "labels"):
            shutil.rmtree(f"{OUT}/{kd}/{sp_}", ignore_errors=True)
    names = []
    for k in range(0, len(ids), SHARD):
        nm = f"s{k // SHARD:04d}"
        sh = {str(f): {"rows": floors[f], "site": meta[f][0], "bldg": meta[f][1],
                       "split": "val" if zlib.crc32(str(meta[f][1]).encode()) % 100 < 8 else "train"} for f in ids[k:k + SHARD]}
        json.dump(sh, open(f"/ds/clean_shards/{nm}.json", "w")); names.append(nm)
    json.dump({"sites": sorted(S), "buildings": sorted(B), "floors": sorted(F)}, open("/ds/clean_shards/excluded.json", "w"))
    vol.commit()
    return {"rows": n_rows, "excluded_rows": n_ex, "floors": len(ids), "sites": len({meta[f][0] for f in ids}),
            "buildings": len({meta[f][1] for f in ids}), "overlap": 0, "shards": names, "excluded_sets":
            {"sites": len(S), "buildings": len(B), "floors": len(F)}, **info}


@app.function(image=image, cpu=1, memory=4096, timeout=1800, volumes={"/ds": vol})
def render_shard(name: str) -> list:
    import os, zlib
    import numpy as np
    import pypdfium2 as pdfium
    import crender, swisslab
    ex = json.load(open("/ds/clean_shards/excluded.json"))
    S, B, F = set(ex["sites"]), set(ex["buildings"]), set(ex["floors"])
    sh = json.load(open(f"/ds/clean_shards/{name}.json"))
    res = []
    for fid, d in sh.items():
        assert int(fid) not in F and d["site"] not in S and d["bldg"] not in B, f"HELD-OUT {fid}"
        sp = d["split"]
        rng = np.random.default_rng(zlib.crc32(f"det{fid}".encode()))
        try:
            r = crender.render_floor(d["rows"], rng)
            if r is None:
                res.append({"floor": fid, "split": sp, "ok": False, "why": "render None"}); continue
            pdf, _, style, info = r
            s = swisslab.PX_PER_M / info["pt_per_m"]
            img = pdfium.PdfDocument(pdf)[0].render(scale=s).to_pil().convert("RGB")
            W, H = img.size
            boxes = []
            for c, x0, y0, x1, y1 in info["inst"]:
                X0, X1 = x0 * s - 1.5, x1 * s + 1.5
                Y0, Y1 = (info["H"] - y1) * s - 1.5, (info["H"] - y0) * s + 1.5
                X0, Y0, X1, Y1 = max(0, X0), max(0, Y0), min(W, X1), min(H, Y1)
                if X1 - X0 >= 3 and Y1 - Y0 >= 3:
                    boxes.append((c, X0, Y0, X1, Y1))
            T = swisslab.tiles(img, boxes, keep_empty=0.15 if sp == "train" else 1.0, seed=int(fid) & 0xffff)
            os.makedirs(f"{OUT}/images/{sp}", exist_ok=True); os.makedirs(f"{OUT}/labels/{sp}", exist_ok=True)
            per = [0, 0, 0]
            for suf, crop, bb in T:
                crop.save(f"{OUT}/images/{sp}/c{fid}{suf}.png")
                with open(f"{OUT}/labels/{sp}/c{fid}{suf}.txt", "w") as f:
                    for c, a0, b0, a1, b1 in bb:
                        per[c] += 1
                        f.write(f"{c} {(a0 + a1) / 2 / swisslab.TILE:.6f} {(b0 + b1) / 2 / swisslab.TILE:.6f} "
                                f"{(a1 - a0) / swisslab.TILE:.6f} {(b1 - b0) / swisslab.TILE:.6f}\n")
            res.append({"floor": fid, "split": sp, "ok": True, "tiles": len(T), "per": per, "scale": style.get("scale")})
        except Exception as e:  # noqa: BLE001
            res.append({"floor": fid, "split": sp, "ok": False, "why": f"{type(e).__name__}: {e}"[:160]})
    vol.commit()
    return res


@app.function(image=image, cpu=8, memory=8192, timeout=1800, volumes={"/ds": vol})
def copy_test() -> dict:
    """All 1,040 real dataset Swiss pages (exact DXF labels, from /yolo) -> /yolo_clean/{images,labels}/test/ds_<split>_*."""
    import os, shutil
    from concurrent.futures import ThreadPoolExecutor
    pairs = []
    for sp in ("train", "val", "test"):
        for kind in ("images", "labels"):
            src = f"/ds/yolo/{kind}/{sp}"
            for fn in os.listdir(src):
                pairs.append((f"{src}/{fn}", f"{OUT}/{kind}/test/ds_{sp}_{fn}"))
    os.makedirs(f"{OUT}/images/test", exist_ok=True); os.makedirs(f"{OUT}/labels/test", exist_ok=True)
    with ThreadPoolExecutor(64) as ex:
        list(ex.map(lambda ab: shutil.copyfile(*ab), pairs))
    with open(f"{OUT}/data.yaml", "w") as f:
        f.write(f"path: {OUT}\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n  0: door\n  1: window\n  2: fixture\n")
    vol.commit()
    return {"test_files": len(pairs)}


@app.function(image=image, timeout=600, volumes={"/ds": vol})
def sample_png(split: str, k: int = 0) -> bytes:
    import io, os
    from PIL import Image, ImageDraw
    d = f"{OUT}/labels/{split}"
    cand = sorted(fn for fn in os.listdir(d) if os.path.getsize(f"{d}/{fn}") > 200)
    fn = cand[len(cand) // 3 + k * 7]
    im = Image.open(f"{OUT}/images/{split}/{fn[:-4]}.png").convert("RGB"); dr = ImageDraw.Draw(im)
    for l in open(f"{d}/{fn}"):
        c, cx, cy, w, h = map(float, l.split()); T = im.size[0]
        dr.rectangle([(cx - w / 2) * T, (cy - h / 2) * T, (cx + w / 2) * T, (cy + h / 2) * T],
                     outline=["red", "blue", "green"][int(c)], width=3)
    b = io.BytesIO(); im.resize((800, 800)).save(b, "PNG")
    return b.getvalue()


@app.local_entrypoint()
def main(n_floors: int = 4500, limit_shards: int = 0, frac: int = 3):
    import collections
    p = prep.remote(EXCL_PREVIEW, n_floors, frac)
    names = p.pop("shards")
    print("PREP", json.dumps(p), flush=True)
    if limit_shards:
        names = names[:limit_shards]
    ct = copy_test.spawn()
    rows = [r for out in render_shard.map(names) for r in out]
    t = ct.get()
    ok = [r for r in rows if r["ok"]]
    man = {"prep": p, "floors": dict(collections.Counter(f"{r['split']}:{'ok' if r['ok'] else 'fail'}" for r in rows)),
           "tiles": {s: sum(r["tiles"] for r in ok if r["split"] == s) for s in ("train", "val")},
           "objects": {s: [sum(r["per"][c] for r in ok if r["split"] == s) for c in range(3)] for s in ("train", "val")},
           "fail_reasons": collections.Counter(r.get("why", "")[:50] for r in rows if not r["ok"]).most_common(5),
           "test": t}
    print("MANIFEST", json.dumps(man, indent=1))
    json.dump({"manifest": man, "rows": rows}, open("clean_manifest.json", "w"), indent=0)


@app.local_entrypoint()
def samples():
    import os
    d = os.environ.get("SAMPLES_DIR", "clean_samples")
    os.makedirs(d, exist_ok=True)
    for i, (sp, k) in enumerate((("train", 0), ("val", 1))):
        open(f"{d}/sample{i}_{sp}.png", "wb").write(sample_png.remote(sp, k))
    print("wrote", d)
