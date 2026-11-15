"""YOLO11l detector (door, window, fixture) on 3x H100 (DDP), data from the junction-ds volume (built by build.py).
   modal run --detach train.py [--epochs 60] [--smoke]

LOCAL ONLY: nothing here is pushed to GitHub until Awais verifies it and says so.
ultralytics is AGPL-3.0: Awais unbanned it for this run (2026-11-15 04:30); weights/code stay off the deployed app until
he decides the licence question.
Thresholds: per-class confidence picked on VAL (0.15-0.85, max F1). TEST (held-out Swiss sites) is evaluated ONCE at the end.
"""
import modal

app = modal.App("junction-det-train")
vol = modal.Volume.from_name("junction-ds")
image = (modal.Image.debian_slim(python_version="3.12")
         .apt_install("libgl1", "libglib2.0-0")
         .pip_install("torch==2.5.1", "torchvision==0.20.1", "ultralytics==8.3.40", "opencv-python-headless==4.10.0.84", "numpy==1.26.4"))
CLS = ["door", "window", "fixture"]


def _count_labels(root):
    import collections, pathlib
    out = {}
    for sp in ("train", "val", "test"):
        c = collections.Counter(); n = 0
        for f in pathlib.Path(root, "labels", sp).glob("*.txt"):
            n += 1
            for l in f.read_text().split("\n"):
                if l.strip():
                    c[CLS[int(l.split()[0])]] += 1
        out[sp] = {"pages": n, **c}
    return out


def _iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    i = ix * iy; u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i
    return i / u if u > 0 else 0


def _sweep(model, root, split, imgsz, conf_by_cls=None, flat=False):
    """Predict once at conf 0.05; per class, P/R/F1 (IoU>=0.5) and exact-count accuracy per page for each threshold."""
    import pathlib
    from PIL import Image
    idir = pathlib.Path(root, split, "images") if flat else pathlib.Path(root, "images", split)
    ldir = pathlib.Path(root, split, "labels") if flat else pathlib.Path(root, "labels", split)
    imgs = sorted(idir.glob("*.png"))
    ths = [round(0.15 + 0.05 * i, 2) for i in range(15)] if conf_by_cls is None else None
    pages = []
    for i in range(0, len(imgs), 16):
        batch = imgs[i:i + 16]
        for p, r in zip(batch, model.predict([str(x) for x in batch], imgsz=imgsz, conf=0.05, verbose=False, half=True)):
            W, H = Image.open(p).size
            gt = []
            lf = ldir / (p.stem + ".txt")
            for l in (lf.read_text().split("\n") if lf.exists() else []):
                if l.strip():
                    c, cx, cy, w, h = map(float, l.split())
                    gt.append((int(c), [(cx - w / 2) * W, (cy - h / 2) * H, (cx + w / 2) * W, (cy + h / 2) * H]))
            pr = [(int(c), float(s), b.tolist()) for c, s, b in zip(r.boxes.cls.cpu(), r.boxes.conf.cpu(), r.boxes.xyxy.cpu())]
            pages.append((gt, pr))
    out = {}
    for ci, name in enumerate(CLS):
        cand = ths if conf_by_cls is None else [conf_by_cls[name]]
        best = None
        for t in cand:
            tp = fp = fn = exact = 0
            for gt, pr in pages:
                g = [b for c, b in gt if c == ci]; q = sorted([(s, b) for c, s, b in pr if c == ci and s >= t], reverse=True)
                used = set()
                for s, b in q:
                    j = max(((k, _iou(b, gb)) for k, gb in enumerate(g) if k not in used), key=lambda x: x[1], default=(None, 0))
                    if j[0] is not None and j[1] >= 0.5:
                        used.add(j[0]); tp += 1
                    else:
                        fp += 1
                fn += len(g) - len(used); exact += (len(q) == len(g))
            P = tp / max(1, tp + fp); R = tp / max(1, tp + fn); F = 2 * P * R / max(1e-9, P + R)
            row = {"conf": t, "precision": round(P, 4), "recall": round(R, 4), "f1": round(F, 4),
                   "count_exact": round(exact / max(1, len(pages)), 4), "gt": tp + fn}
            if best is None or row["f1"] > best["f1"]:
                best = row
        out[name] = best
    return out


def _private(model, imgsz, conf, viz_dir):
    """Private sheets tiles (never trained on): sheet A = agreement with our rule-based plan map (pseudo-labels, NOT accuracy);
    sheet B = predicted counts only. Annotated tiles saved for a by-eye check."""
    import os, pathlib
    from PIL import Image, ImageDraw
    out = {}
    for sheet in ("private-a", "private-b"):
        d = pathlib.Path("/ds/private_tiles", sheet)
        if not d.exists():
            out[sheet] = "no tiles"; continue
        if (d / "labels").exists() and any((d / "labels").glob("*.txt")):
            agree = _sweep(model, str(d.parent), sheet, imgsz, conf_by_cls=conf, flat=True)
        else:
            agree = None
        counts = {c: 0 for c in CLS}
        os.makedirs(f"{viz_dir}/{sheet}", exist_ok=True)
        imgs = sorted((d / "images").glob("*.png"))
        for i in range(0, len(imgs), 8):
            for p, r in zip(imgs[i:i + 8], model.predict([str(x) for x in imgs[i:i + 8]], imgsz=imgsz, conf=0.05, verbose=False, half=True)):
                im = Image.open(p).convert("RGB"); dr = ImageDraw.Draw(im); n = 0
                for c, sc, b in zip(r.boxes.cls.cpu(), r.boxes.conf.cpu(), r.boxes.xyxy.cpu()):
                    name = CLS[int(c)]
                    if float(sc) >= conf[name]:
                        counts[name] += 1; n += 1
                        dr.rectangle(b.tolist(), outline=["red", "blue", "green"][int(c)], width=3)
                        dr.text((float(b[0]), float(b[1]) - 10), f"{name} {float(sc):.2f}", fill="black")
                if n:
                    im.save(f"{viz_dir}/{sheet}/{p.name}")
        out[sheet] = {"agreement_with_rule_based_plan_map": agree, "predicted_counts_tiles_overlap": counts,
                      "note": "tiles overlap by 256 px, so counts include some duplicates; not accuracy"}
    return out


@app.function(image=image, gpu="H100:3", volumes={"/ds": vol}, timeout=8 * 3600, cpu=36, memory=196608)
def train(epochs: int = 100, imgsz: int = 1280, batch: int = 48, smoke: bool = False):
    import json, time
    from ultralytics import YOLO
    import shutil
    t_copy = time.time()
    import os
    from concurrent.futures import ThreadPoolExecutor
    pairs = []
    for dp, _, fs in os.walk("/ds/yolo"):
        for fn in fs:
            if fn.endswith((".png", ".txt")):
                src = os.path.join(dp, fn); pairs.append((src, "/tmp/yolo" + src[len("/ds/yolo"):]))
    for d in {os.path.dirname(b) for _, b in pairs}:
        os.makedirs(d, exist_ok=True)
    with ThreadPoolExecutor(96) as ex:  # many parallel reads: the volume is slow per file, fast in aggregate
        list(ex.map(lambda ab: shutil.copyfile(*ab), pairs))
    print("copied", len(pairs), "files", flush=True)
    root = "/tmp/yolo"  # local NVMe copy: the network volume is far too slow for per-epoch reads
    with open(f"{root}/data.yaml", "w") as f:
        f.write(f"path: {root}\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n  0: door\n  1: window\n  2: fixture\n")
    print("copied dataset to local disk in", round(time.time() - t_copy, 1), "s", flush=True)
    counts = _count_labels(root)
    print("label counts", json.dumps(counts), flush=True)
    for sp in ("train", "val", "test"):
        for c in CLS:
            assert counts[sp].get(c, 0) > 0, f"no {c} labels in {sp}: the build failed silently"
    t0 = time.time()
    run = "smoke" if smoke else "y11l"
    model = YOLO("yolo11l.pt")
    model.train(data=f"{root}/data.yaml", epochs=1 if smoke else epochs, imgsz=imgsz, batch=batch, device=[0, 1, 2],
                patience=25, save_period=10, cos_lr=True, close_mosaic=10, scale=0.1, fliplr=0.5, flipud=0.0, degrees=0.0,
                hsv_h=0.0, hsv_s=0.0, hsv_v=0.2, mosaic=1.0, workers=10, cache="ram", project="/ds/runs", name=run, exist_ok=True,
                fraction=0.05 if smoke else 1.0, plots=False, verbose=False)
    vol.commit()
    best = YOLO(f"/ds/runs/{run}/weights/best.pt")
    val = _sweep(best, root, "val", imgsz)
    print("VAL (thresholds picked here)", json.dumps(val), flush=True)
    conf = {k: v["conf"] for k, v in val.items()}
    test = _sweep(best, root, "test", imgsz, conf_by_cls=conf)  # held-out: once
    m = best.val(data=f"{root}/data.yaml", split="test", imgsz=imgsz, batch=16, plots=False, verbose=False)
    res = {"counts": counts, "val": val, "conf": conf, "test": test,
           "test_map50": round(float(m.box.map50), 4), "test_map50_95": round(float(m.box.map), 4),
           "test_map50_per_class": {CLS[i]: round(float(x), 4) for i, x in enumerate(m.box.ap50)},
           "minutes": round((time.time() - t0) / 60, 1), "epochs": epochs, "imgsz": imgsz, "batch": batch}
    res["private"] = _private(best, imgsz, conf, f"/ds/runs/{run}/private_viz")
    json.dump(res, open(f"/ds/runs/{run}/result.json", "w"), indent=1)
    vol.commit()
    print("RESULT", json.dumps(res), flush=True)
    return res


@app.local_entrypoint()
def main(epochs: int = 60, smoke: bool = False):
    print(train.remote(epochs=epochs, smoke=smoke))
