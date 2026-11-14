"""V-08: ONNX export + parity + CPU timing.
  .venv/bin/python vision/export_onnx.py seg [weights.safetensors]   -> weights/onnx/unet.onnx
  .venv/bin/python vision/export_onnx.py det [hf_dir]                -> weights/onnx/rtdetr.onnx
Parity: max abs diff / argmax agreement vs PyTorch on the 4 cubicasa fixtures; CPU ms/img via onnxruntime. Writes results/vision/onnx_<kind>.json."""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import numpy as np, torch
from PIL import Image
import infer, build_planmaps as B
ROOT = infer.ROOT
OUT = ROOT / "weights/onnx"; OUT.mkdir(parents=True, exist_ok=True)
fx = [f for f in json.loads((ROOT / "tests/fixtures.json").read_text()) if f.startswith("cubicasa5k__")][:3]
imgs = [Image.open(B.image_path(d)).convert("RGB") for d in fx]
import onnxruntime as ort


def timed(fn, n=3):
    fn(); t = time.perf_counter()
    for _ in range(n): fn()
    return (time.perf_counter() - t) / n * 1000


def seg(w):
    from safetensors.torch import load_file
    from unet_resnet34 import UNetResNet34
    m = UNetResNet34(4); m.load_state_dict(load_file(str(w or ROOT / "weights/yytsi_unet/best.safetensors")), strict=True); m.eval()
    x0 = torch.zeros(1, 3, 512, 512)
    torch.onnx.export(m, x0, str(OUT / "unet.onnx"), input_names=["x"], output_names=["y"], opset_version=17, dynamo=False)
    s = ort.InferenceSession(str(OUT / "unet.onnx"), providers=["CPUExecutionProvider"])
    diffs, agree = [], []
    for img in imgs:
        box, _ = infer._letterbox(img, 512, (124, 116, 104))
        x = torch.from_numpy(((np.asarray(box, np.float32) / 255 - infer.SegModel.MEAN) / infer.SegModel.STD).transpose(2, 0, 1)).float()[None]
        with torch.no_grad(): a = m(x).numpy()
        b = s.run(None, {"x": x.numpy()})[0]
        diffs.append(float(np.abs(a - b).max())); agree.append(float((a.argmax(1) == b.argmax(1)).mean()))
    ms = timed(lambda: s.run(None, {"x": x.numpy()}))
    return {"max_abs_diff": diffs, "argmax_agreement": agree, "onnx_cpu_ms": round(ms), "torch_mps_ms_note": "see results/vision/timing.json"}


def det(d):
    from transformers import RTDetrForObjectDetection, RTDetrImageProcessor
    m = RTDetrForObjectDetection.from_pretrained(d).eval()
    proc = RTDetrImageProcessor.from_pretrained(d, size={"height": 1024, "width": 1024}, do_resize=True)
    class Wrap(torch.nn.Module):
        def __init__(s, m): super().__init__(); s.m = m
        def forward(s, x):
            o = s.m(pixel_values=x); return o.logits, o.pred_boxes
    w = Wrap(m).eval(); x0 = torch.zeros(1, 3, 1024, 1024)
    torch.onnx.export(w, x0, str(OUT / "rtdetr.onnx"), input_names=["x"], output_names=["logits", "boxes"], opset_version=17, dynamo=False)
    s = ort.InferenceSession(str(OUT / "rtdetr.onnx"), providers=["CPUExecutionProvider"])
    dl, db, agree = [], [], []
    for img in imgs:
        x = proc(images=img, return_tensors="pt")["pixel_values"]
        with torch.no_grad(): l, b = w(x)
        ol, ob = s.run(None, {"x": x.numpy()})
        dl.append(float(np.abs(l.numpy() - ol).max())); db.append(float(np.abs(b.numpy() - ob).max()))
        agree.append(float((l.sigmoid().numpy().max(-1) > 0.5).sum() == (1 / (1 + np.exp(-ol))).max(-1).__gt__(0.5).sum()))
    ms = timed(lambda: s.run(None, {"x": x.numpy()}), 2)
    return {"max_abs_diff_logits": dl, "max_abs_diff_boxes": db, "same_detection_count_at_0.5": agree, "onnx_cpu_ms": round(ms)}


if __name__ == "__main__":
    k = sys.argv[1]; r = seg(sys.argv[2] if len(sys.argv) > 2 else None) if k == "seg" else det(sys.argv[2])
    r["fixtures"] = fx; (ROOT / f"results/vision/onnx_{k}.json").write_text(json.dumps(r, indent=1)); print(json.dumps(r, indent=1))
