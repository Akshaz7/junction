"""V-07: fine-tune RT-DETR (Apache-2.0, PekingU/rtdetr_r50vd via transformers) for door/window/toilet/sink/shower/bathtub on Modal.

  modal volume create junction-v05 ; modal volume put junction-v05 data/train/v05 /v05 --force     # once per rebuild of the set
  modal run train/modal_det.py --smoke               # 2-minute smoke test
  modal run train/modal_det.py                       # full run, hard cap 2 GPU-hours (timeout 7200 s, internal stop at 105 min)
  modal volume get junction-vision-out det/best /tmp/det_best     # then copy to weights/rtdetr_ft/

Zero-overlap: refuses to start unless results/vision/v05_overlap.json-style check passes: the held-out lists are uploaded with the data and re-checked
against every training record's origin before the first step. No assert, no training.
"""
import modal

app = modal.App("junction-v07-det")
vol_data = modal.Volume.from_name("junction-v05", create_if_missing=True)
vol_out = modal.Volume.from_name("junction-vision-out", create_if_missing=True)
image = (modal.Image.debian_slim(python_version="3.12")
         .pip_install("torch==2.5.1", "torchvision==0.20.1", "transformers==4.46.3", "pillow", "numpy", "scipy", "accelerate")
         .add_local_dir("train", "/root/train", ignore=["__pycache__"])
         .add_local_dir("data/sets", "/root/sets"))  # held-out lists, uploaded with the code

MINUTES_CAP = 105


@app.function(image=image, gpu="L40S", timeout=7200, volumes={"/data": vol_data, "/out": vol_out})
def train(smoke: bool = False, epochs: int = 40, lr: float = 1e-4, size: int = 1024, bs: int = 4):
    import json, random, sys, time
    sys.path.insert(0, "/root/train")
    import numpy as np, torch
    from vdata import DET_KINDS, augment, clip_box, load_records, open_img
    from transformers import RTDetrForObjectDetection, RTDetrImageProcessor

    root = "/data/v05"
    # ---- zero-overlap assert (fresh load)
    held_ids = {l.strip() for l in open("/root/sets/cubicasa_heldout_ids.txt") if l.strip()}
    held_docs = {l.strip() for l in open("/root/sets/heldout_docs.txt") if l.strip()}
    assert len(held_ids) >= 4000 and len(held_docs) >= 4000, "held-out lists incomplete"
    recs = [json.loads(l) for l in open(f"{root}/labels.jsonl")]
    for r in recs:
        o = r["origin"]
        assert not (r["source"] == "cubicasa5k_clean" and o in held_ids), f"held-out overlap {o}"
        assert not (r["source"] == "synthetic" and o in held_docs), f"held-out overlap {o}"
    print("zero-overlap OK:", len(recs), "records vs", len(held_ids), "ids /", len(held_docs), "docs", flush=True)

    proc = RTDetrImageProcessor.from_pretrained("PekingU/rtdetr_r50vd", size={"height": size, "width": size}, do_resize=True)
    cid = {k: i for i, k in enumerate(DET_KINDS)}
    model = RTDetrForObjectDetection.from_pretrained("PekingU/rtdetr_r50vd", num_labels=len(DET_KINDS), id2label={i: k for k, i in cid.items()}, label2id=cid, ignore_mismatched_sizes=True).cuda()
    tr, va = load_records(root, "train"), load_records(root, "val")
    if smoke:
        tr, va, epochs = tr[:16], va[:8], 1
    else:  # CubiCasa is the target domain but tiny (56 drawings): oversample x4
        tr = tr + 3 * [r for r in tr if r["source"] == "cubicasa5k_clean"]
    rnd = random.Random(0)

    def batch(rs, train_):
        imgs, labels = [], []
        for r in rs:
            img, items = augment(open_img(root, r), [i for i in r["items"] if i["kind"] in cid], rnd, train_)
            W, H = img.size
            boxes, cls = [], []
            for i in items:
                b = clip_box(i["bbox_px"], W, H)
                if b:
                    boxes.append([(b[0] + b[2]) / 2 / W, (b[1] + b[3]) / 2 / H, (b[2] - b[0]) / W, (b[3] - b[1]) / H]); cls.append(cid[i["kind"]])
            imgs.append(img)
            labels.append({"class_labels": torch.tensor(cls, dtype=torch.long), "boxes": torch.tensor(boxes, dtype=torch.float32).reshape(-1, 4)})
        px = proc(images=imgs, return_tensors="pt")["pixel_values"].cuda()
        return px, [{k: v.cuda() for k, v in l.items()} for l in labels]

    opt = torch.optim.AdamW([{"params": [p for n, p in model.named_parameters() if "backbone" in n], "lr": lr * 0.1},
                             {"params": [p for n, p in model.named_parameters() if "backbone" not in n], "lr": lr}], weight_decay=1e-4)
    t0, best, step = time.time(), -1.0, 0

    @torch.no_grad()
    def evaluate():
        model.eval(); tp = fp = fn = 0
        for s in range(0, len(va), bs):
            rs = va[s:s + bs]
            px, labels = batch(rs, False)
            out = model(pixel_values=px)
            res = proc.post_process_object_detection(out, threshold=0.5, target_sizes=torch.tensor([[1.0, 1.0]] * len(rs)))
            for lab, rr in zip(labels, res):
                gt = [(int(c), b) for c, b in zip(lab["class_labels"].cpu(), lab["boxes"].cpu())]
                used = set()
                for sc, c, b in zip(rr["scores"].cpu(), rr["labels"].cpu(), rr["boxes"].cpu()):
                    hit = False
                    for gi, (gc, gb) in enumerate(gt):
                        if gi in used or gc != int(c):
                            continue
                        gx0, gy0, gx1, gy1 = gb[0] - gb[2] / 2, gb[1] - gb[3] / 2, gb[0] + gb[2] / 2, gb[1] + gb[3] / 2
                        ix = max(0, min(b[2], gx1) - max(b[0], gx0)); iy = max(0, min(b[3], gy1) - max(b[1], gy0))
                        inter = ix * iy; u = (b[2] - b[0]) * (b[3] - b[1]) + gb[2] * gb[3] - inter
                        if u > 0 and inter / u >= 0.5:
                            used.add(gi); hit = True; break
                    tp += hit; fp += (not hit)
                fn += len(gt) - len(used)
        model.train()
        p = tp / max(1, tp + fp); r_ = tp / max(1, tp + fn)
        return {"precision": p, "recall": r_, "f1": 2 * p * r_ / max(1e-9, p + r_)}

    model.train()
    for ep in range(epochs):
        rnd.shuffle(tr)
        for s in range(0, len(tr) - bs + 1, bs):
            px, labels = batch(tr[s:s + bs], True)
            loss = model(pixel_values=px, labels=labels).loss
            opt.zero_grad(); loss.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(), 0.1); opt.step(); step += 1
            if step % 20 == 0:
                print(f"ep {ep} step {step} loss {loss.item():.3f} min {(time.time() - t0) / 60:.1f}", flush=True)
            if (time.time() - t0) / 60 > (1.5 if smoke else MINUTES_CAP):
                break
        m = evaluate(); print("val", ep, m, flush=True)
        if m["f1"] > best:
            best = m["f1"]; model.save_pretrained("/out/det/best"); proc.save_pretrained("/out/det/best")
            json.dump({"epoch": ep, "val": m, "kinds": DET_KINDS, "records": len(recs), "minutes": (time.time() - t0) / 60}, open("/out/det/best/train_info.json", "w"))
            vol_out.commit()
        if (time.time() - t0) / 60 > (1.5 if smoke else MINUTES_CAP):
            print("time cap reached", flush=True); break
    vol_out.commit()
    return {"best_f1": best, "minutes": (time.time() - t0) / 60}


@app.local_entrypoint()
def main(smoke: bool = False):
    print(train.remote(smoke=smoke))
