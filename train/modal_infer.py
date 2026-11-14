"""V-07 full held-out inference: run the fine-tuned RT-DETR over all 4,787 held-out CubiCasa drawings (pre-resized 1024x1024, volume junction-v05:/full_eval).

  modal run train/modal_infer.py          # writes /out/det_full_dets.json (normalised boxes, floor 0.2), then:
  modal volume get junction-vision-out det_full_dets.json results/vision/det_full_dets.json
Inference only: no training, no tuning on these drawings.
"""
import modal

app = modal.App("junction-v07-infer")
vol_data = modal.Volume.from_name("junction-v05")
vol_out = modal.Volume.from_name("junction-vision-out")
image = (modal.Image.debian_slim(python_version="3.12")
         .pip_install("torch==2.5.1", "torchvision==0.20.1", "transformers==4.46.3", "pillow", "numpy", "scipy", "accelerate"))


@app.function(image=image, gpu="L40S", timeout=3600, volumes={"/data": vol_data, "/out": vol_out})
def infer(weights: str = "/out/det/best", limit: int = 10**9):
    import json, os, time, torch
    from PIL import Image
    from transformers import RTDetrForObjectDetection, RTDetrImageProcessor
    proc = RTDetrImageProcessor.from_pretrained(weights, size={"height": 1024, "width": 1024}, do_resize=True)
    m = RTDetrForObjectDetection.from_pretrained(weights).cuda().eval().half()
    id2 = m.config.id2label
    files = sorted(os.listdir("/data/full_eval"))[:limit]
    out, t0, bs = {}, time.time(), 8
    for s in range(0, len(files), bs):
        fs = files[s:s + bs]
        imgs = [Image.open(f"/data/full_eval/{f}").convert("RGB") for f in fs]
        px = proc(images=imgs, return_tensors="pt")["pixel_values"].cuda().half()
        with torch.no_grad():
            o = m(pixel_values=px)
        o.logits, o.pred_boxes = o.logits.float(), o.pred_boxes.float()
        rs = proc.post_process_object_detection(o, threshold=0.2, target_sizes=torch.tensor([[1.0, 1.0]] * len(fs)))
        for f, r in zip(fs, rs):
            out[f[:-4]] = [dict(kind=id2[int(l)], conf=round(float(sc), 3), box=[round(float(v), 5) for v in b]) for sc, l, b in zip(r["scores"].cpu(), r["labels"].cpu(), r["boxes"].cpu())]
    json.dump(out, open("/out/det_full_dets.json", "w")); vol_out.commit()
    return {"n": len(out), "minutes": round((time.time() - t0) / 60, 2)}


@app.local_entrypoint()
def main(limit: int = 10**9):
    print(infer.remote(limit=limit))
