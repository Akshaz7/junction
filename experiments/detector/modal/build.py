"""Build the YOLO tile dataset on the junction-ds volume from the full Junction dataset (already on the volume).
   modal run build.py [--limit N]
LOCAL ONLY: nothing here is pushed until Awais verifies it and says so.

Labels: Swiss PDF+DXF twins only (exact DOOR / WINDOW / FIXTURE layers; FIXTURE includes stairs and kitchen units).
Every page is rendered at 40 px per metre and cut into 1280 px tiles (stride 1024).
Split BY BUILDING:
  test  = buildings whose site is in excluded_swiss.json (our preview held-out) + ~10 % of buildings (crc32 of the id)
  val   = another ~10 % of buildings (threshold picking only)
  train = the rest. NOTE: all 1,040 dataset Swiss drawings are referenced by questions.jsonl (Awais chose to train on
          them, 05:00), so answers to those questions are not held-out results.
Private sheets (not in the repo) are NOT in any train/val split (): they are rendered the same way into
/ds/private_tiles/ and used only as a post-training test (sheet A pseudo-labels = agreement with our rule-based plan map, not accuracy).
"""
import json
import os

import modal

app = modal.App("junction-det-build")
vol = modal.Volume.from_name("junction-ds")
image = (modal.Image.debian_slim(python_version="3.12")
         .pip_install("numpy==2.1.3", "pillow==11.0.0", "pypdfium2==4.30.0", "ezdxf==1.3.4")
         .add_local_python_source("swisslab"))
DS = "/ds/full/junction-dataset"
OUT = "/ds/yolo"
EXCL = json.load(open(os.environ.get("EXCLUDED_SWISS_JSON", "excluded_swiss.json"))) \
    if modal.is_local() else {}


def _ids(stem):
    import re
    m = re.match(r"site(\d+)_bldg(\d+)", stem)
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


@app.function(image=image, volumes={"/ds": vol}, timeout=600)
def plan_splits(held_sites: list) -> dict:
    import pathlib, zlib
    d = pathlib.Path(DS, "data/swiss_dwellings")
    stems = sorted({p.stem for p in d.glob("*.pdf")} & {p.stem for p in d.glob("*.dxf")})
    asked = set()
    for l in open(f"{DS}/questions.jsonl"):
        q = json.loads(l)
        if "swiss_dwellings/" in q["path"]:
            asked.add(q["path"].rsplit("/", 1)[-1].rsplit(".", 1)[0])
    held = set(held_sites)
    # train on the dataset's Swiss PDFs (all 1,040 are referenced by questions.jsonl, so benchmark
    # numbers on them are NOT held-out). Our own held-out: whole buildings, never trained on or tuned on.
    test_b = {_ids(s)[1] for s in stems if _ids(s)[0] in held}
    split = {}
    for s in stems:
        b = _ids(s)[1]; h = zlib.crc32(str(b).encode()) % 100
        split[s] = "test" if (b in test_b or h < 10) else ("val" if h < 20 else "train")
    return {"split": split, "n_asked": len(asked & set(stems)), "n_pairs": len(stems)}


@app.function(image=image, volumes={"/ds": vol}, timeout=1800, cpu=2, memory=6144)
def label_batch(items: list) -> list:
    import os, swisslab
    res = []
    for stem, sp in items:
        base = f"{DS}/data/swiss_dwellings/{stem}"
        try:
            img, boxes, info = swisslab.label_pair(base + ".pdf", base + ".dxf")
        except Exception as e:  # noqa: BLE001
            res.append({"stem": stem, "split": sp, "ok": False, "why": f"{type(e).__name__}: {e}"[:200]}); continue
        if img is None:
            res.append({"stem": stem, "split": sp, "ok": False, **info}); continue
        os.makedirs(f"{OUT}/images/{sp}", exist_ok=True); os.makedirs(f"{OUT}/labels/{sp}", exist_ok=True)
        T = swisslab.tiles(img, boxes, keep_empty=0.15 if sp == "train" else 1.0, seed=hash(stem) & 0xffff)
        per = [0, 0, 0]
        for suf, crop, bb in T:
            crop.save(f"{OUT}/images/{sp}/{stem}{suf}.png")
            with open(f"{OUT}/labels/{sp}/{stem}{suf}.txt", "w") as f:
                for c, x0, y0, x1, y1 in bb:
                    per[c] += 1
                    f.write(f"{c} {(x0 + x1) / 2 / swisslab.TILE:.6f} {(y0 + y1) / 2 / swisslab.TILE:.6f} "
                            f"{(x1 - x0) / swisslab.TILE:.6f} {(y1 - y0) / swisslab.TILE:.6f}\n")
        res.append({"stem": stem, "split": sp, "ok": True, "n": len(boxes), "tiles": len(T), "per_cls_tiles": per, **info})
    vol.commit()
    return res


@app.function(image=image, volumes={"/ds": vol}, timeout=900, memory=8192)
def private_tiles() -> dict:
    """Private sheets at 40 px/m (printed 1:100) -> /ds/private_tiles/<sheet>/{images,labels}; test only, never trained on."""
    import os, re, pypdfium2 as pdfium, swisslab
    out = {}
    for sheet, lab in (("private-a", "/ds/private/private-a.txt"), ("private-b", None)):
        pg = pdfium.PdfDocument(f"/ds/private/{sheet}.pdf")[0]
        txt = pg.get_textpage().get_text_range()
        m = re.findall(r"1\s*:\s*(\d{2,3})\b", txt)
        ratio = 100 if not m else max(set(m), key=m.count)
        ratio = int(ratio)
        img = pg.render(scale=swisslab.dpi_for(ratio) / 72).to_pil().convert("RGB")
        W, H = img.size
        boxes = []
        if lab:
            for l in open(lab).read().split("\n"):
                if l.strip():
                    c, cx, cy, w, h = map(float, l.split())
                    boxes.append((int(c), (cx - w / 2) * W, (cy - h / 2) * H, (cx + w / 2) * W, (cy + h / 2) * H))
        T = swisslab.tiles(img, boxes, keep_empty=1.0)
        d = f"/ds/private_tiles/{sheet}"
        os.makedirs(f"{d}/images", exist_ok=True); os.makedirs(f"{d}/labels", exist_ok=True)
        for suf, crop, bb in T:
            crop.save(f"{d}/images/{sheet}{suf}.png")
            if lab:
                with open(f"{d}/labels/{sheet}{suf}.txt", "w") as f:
                    for c, x0, y0, x1, y1 in bb:
                        f.write(f"{c} {(x0 + x1) / 2 / swisslab.TILE:.6f} {(y0 + y1) / 2 / swisslab.TILE:.6f} "
                                f"{(x1 - x0) / swisslab.TILE:.6f} {(y1 - y0) / swisslab.TILE:.6f}\n")
        out[sheet] = {"printed_ratios": sorted(set(m))[:6], "ratio_used": ratio, "px": [W, H], "tiles": len(T),
                      "pseudo_boxes": len(boxes)}
    vol.commit()
    return out


@app.function(image=image, volumes={"/ds": vol}, timeout=300)
def write_yaml():
    with open(f"{OUT}/data.yaml", "w") as f:
        f.write(f"path: {OUT}\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n  0: door\n  1: window\n  2: fixture\n")
    vol.commit()


@app.local_entrypoint()
def main(limit: int = 0, per: int = 20):
    import collections
    sp = plan_splits.remote(EXCL.get("sites", []))
    items = sorted(sp["split"].items())
    if limit:
        items = items[:limit]
    print("pairs", sp["n_pairs"], "asked by questions", sp["n_asked"], "splits", dict(collections.Counter(sp["split"].values())), flush=True)
    chunks = [items[i:i + per] for i in range(0, len(items), per)]
    jt = private_tiles.spawn()
    rows = [r for out in label_batch.map(chunks) for r in out]
    write_yaml.remote()
    private = jt.get()
    man = {"pages": dict(collections.Counter(f"{r['split']}:{'ok' if r['ok'] else 'dropped'}" for r in rows)),
           "tiles": {s: sum(r.get("tiles", 0) for r in rows if r["split"] == s) for s in ("train", "val", "test")},
           "objects_per_class_in_tiles": {s: [sum(r["per_cls_tiles"][c] for r in rows if r["ok"] and r["split"] == s) for c in range(3)]
                                          for s in ("train", "val", "test")},
           "buildings": {s: len({_ids(r["stem"])[1] for r in rows if r["split"] == s}) for s in ("train", "val", "test")},
           "dropped_reasons": collections.Counter((r.get("why") or "")[:40] for r in rows if not r["ok"]).most_common(6),
           "private_test_only": private}
    print("MANIFEST", json.dumps(man, indent=1))
    json.dump({"manifest": man, "rows": rows}, open("build_manifest.json", "w"), indent=0)


@app.local_entrypoint()
def splits():
    import collections
    sp = plan_splits.remote(EXCL.get("sites", []))
    b = collections.defaultdict(set)
    for s, v in sp["split"].items():
        b[v].add(_ids(s)[1])
    print("pairs", sp["n_pairs"], "asked", sp["n_asked"], "pages", dict(collections.Counter(sp["split"].values())),
          "buildings", {k: len(v) for k, v in b.items()})
