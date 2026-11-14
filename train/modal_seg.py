"""V-06: fine-tune the ResNet34-UNet (Yytsi, MIT; 4 classes floor/wall/door/window) on the V-05 set, on Modal. Only records with polygon/box masks
(clean CubiCasa5K + DATA synthetic; FloorPlanCAD has boxes only).

  modal volume put junction-v05 data/train/v05 /v05 --force
  modal volume put junction-v05 weights/yytsi_unet/best.safetensors /yytsi_best.safetensors --force
  modal run train/modal_seg.py --smoke          # short smoke test
  modal run train/modal_seg.py                  # full run, hard cap 2 GPU-hours (timeout 7200 s, internal stop at 100 min)
  modal volume get junction-vision-out seg/best.safetensors weights/unet_ft/best.safetensors

Same zero-overlap assert as V-07 (held-out lists re-read before the first step).
"""
import modal

app = modal.App("junction-v06-seg")
vol_data = modal.Volume.from_name("junction-v05", create_if_missing=True)
vol_out = modal.Volume.from_name("junction-vision-out", create_if_missing=True)
image = (modal.Image.debian_slim(python_version="3.12")
         .pip_install("torch==2.5.1", "torchvision==0.20.1", "safetensors", "pillow", "numpy")
         .add_local_dir("train", "/root/train", ignore=["__pycache__"])
         .add_local_file("vision/unet_resnet34.py", "/root/train/unet_resnet34.py")
         .add_local_dir("data/sets", "/root/sets"))
MINUTES_CAP = 100


@app.function(image=image, gpu="L4", timeout=7200, volumes={"/data": vol_data, "/out": vol_out})
def train(smoke: bool = False, epochs: int = 60, lr: float = 2e-4, size: int = 512, bs: int = 8):
    import json, random, sys, time
    sys.path.insert(0, "/root/train")
    import numpy as np, torch, torch.nn.functional as F
    from PIL import Image
    from safetensors.torch import load_file, save_file
    from unet_resnet34 import UNetResNet34
    from vdata import augment, load_records, open_img, seg_mask

    root = "/data/v05"
    held_ids = {l.strip() for l in open("/root/sets/cubicasa_heldout_ids.txt") if l.strip()}
    held_docs = {l.strip() for l in open("/root/sets/heldout_docs.txt") if l.strip()}
    assert len(held_ids) >= 4000 and len(held_docs) >= 4000, "held-out lists incomplete"
    for l in open(f"{root}/labels.jsonl"):
        r = json.loads(l)
        assert not (r["source"] == "cubicasa5k_clean" and r["origin"] in held_ids), f"held-out overlap {r['origin']}"
        assert not (r["source"] == "synthetic" and r["origin"] in held_docs), f"held-out overlap {r['origin']}"
    print("zero-overlap OK", flush=True)

    tr, va = load_records(root, "train", True), load_records(root, "val", True)
    if smoke:
        tr, va, epochs = tr[:16], va[:8], 1
    model = UNetResNet34(4).cuda()
    model.load_state_dict(load_file("/data/yytsi_best.safetensors"), strict=True)
    mean = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1).cuda(); std = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1).cuda()
    rnd = random.Random(0)

    def letter(img, mask):
        W, H = img.size; s = size / max(W, H)
        nw, nh = max(1, round(W * s)), max(1, round(H * s))
        canvas = Image.new("RGB", (size, size), (255, 255, 255)); canvas.paste(img.resize((nw, nh), Image.BILINEAR), (0, 0))
        m = Image.new("L", (size, size), 0); m.paste(mask.resize((nw, nh), Image.NEAREST), (0, 0))
        return canvas, m

    def batch(rs, train_):
        xs, ys = [], []
        for r in rs:
            img, items = augment(open_img(root, r), r["items"], rnd, train_)
            x, y = letter(img, seg_mask(img.size, items))
            xs.append(np.asarray(x)); ys.append(np.asarray(y))
        x = torch.from_numpy(np.stack(xs)).permute(0, 3, 1, 2).float().cuda() / 255
        return (x - mean) / std, torch.from_numpy(np.stack(ys)).long().cuda()

    def dice(logits, y):
        p = logits.softmax(1); oh = F.one_hot(y, 4).permute(0, 3, 1, 2).float()
        inter = (p * oh).sum((0, 2, 3)); den = p.sum((0, 2, 3)) + oh.sum((0, 2, 3))
        return 1 - ((2 * inter + 1) / (den + 1)).mean()

    @torch.no_grad()
    def evaluate():
        model.eval(); inter = torch.zeros(4); union = torch.zeros(4)
        for s in range(0, len(va), bs):
            x, y = batch(va[s:s + bs], False); pr = model(x).argmax(1)
            for c in range(4):
                inter[c] += ((pr == c) & (y == c)).sum().cpu(); union[c] += ((pr == c) | (y == c)).sum().cpu()
        model.train(); iou = (inter / union.clamp(min=1)).tolist()
        return {"iou": dict(zip(["floor", "wall", "door", "window"], [round(v, 3) for v in iou])), "miou": round(sum(iou) / 4, 4)}

    base = evaluate(); print("val before fine-tune", base, flush=True)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    w = torch.tensor([0.5, 1.0, 2.0, 2.0]).cuda()
    t0, best = time.time(), base["miou"]
    model.train()
    for ep in range(epochs):
        rnd.shuffle(tr)
        for s in range(0, len(tr) - bs + 1, bs):
            x, y = batch(tr[s:s + bs], True); lg = model(x)
            loss = F.cross_entropy(lg, y, weight=w) + dice(lg, y)
            opt.zero_grad(); loss.backward(); opt.step()
        m = evaluate(); print("ep", ep, "loss", round(loss.item(), 3), "val", m, f"min {(time.time() - t0) / 60:.1f}", flush=True)
        if m["miou"] > best:
            best = m["miou"]
            import os; os.makedirs("/out/seg", exist_ok=True)
            save_file({k: v.contiguous().cpu() for k, v in model.state_dict().items()}, "/out/seg/best.safetensors")
            json.dump({"epoch": ep, "val": m, "baseline_val": base, "minutes": (time.time() - t0) / 60}, open("/out/seg/train_info.json", "w")); vol_out.commit()
        if (time.time() - t0) / 60 > (1.0 if smoke else MINUTES_CAP):
            print("time cap reached", flush=True); break
    vol_out.commit()
    return {"baseline": base, "best_miou": best, "minutes": (time.time() - t0) / 60}


@app.local_entrypoint()
def main(smoke: bool = False):
    print(train.remote(smoke=smoke))
