"""Post-training evaluation on one H100 (fresh weights per phase; fixes the half-precision crash after model.val).
   modal run evaluate.py --run y11l --data yolo          # experiment run (trained on question-referenced Swiss)
   modal run evaluate.py --run y11l_clean --data yolo_clean
VAL -> per-class thresholds (0.15-0.85, max F1). TEST once with those thresholds. private sheets: agreement with the vector
plan map (pseudo-labels) + predicted counts + marked-up tiles (by-eye check). Writes /ds/runs/<run>/result.json.
LOCAL ONLY: nothing pushed.
"""
import modal

app = modal.App("junction-det-eval")
vol = modal.Volume.from_name("junction-ds")
image = (modal.Image.debian_slim(python_version="3.12")
         .apt_install("libgl1", "libglib2.0-0")
         .pip_install("torch==2.5.1", "torchvision==0.20.1", "ultralytics==8.3.40", "opencv-python-headless==4.10.0.84",
                      "numpy==1.26.4")
         .add_local_python_source("train"))


@app.function(image=image, gpu="H100", volumes={"/ds": vol}, timeout=3 * 3600, cpu=16, memory=65536)
def evaluate(run: str, data: str, imgsz: int = 1280):
    import json, os, shutil, time
    from concurrent.futures import ThreadPoolExecutor
    from ultralytics import YOLO
    import train as T
    t0 = time.time()
    vol.reload()
    src = f"/ds/{data}"
    pairs = []
    for dp, _, fs in os.walk(src):
        if "/images/train" in dp or "/labels/train" in dp:
            continue
        for fn in fs:
            if fn.endswith((".png", ".txt")):
                a = os.path.join(dp, fn); pairs.append((a, "/tmp/d" + a[len(src):]))
    for d in {os.path.dirname(b) for _, b in pairs}:
        os.makedirs(d, exist_ok=True)
    with ThreadPoolExecutor(96) as ex:
        list(ex.map(lambda ab: shutil.copyfile(*ab), pairs))
    root = "/tmp/d"
    w = f"/ds/runs/{run}/weights/best.pt"
    val = T._sweep(YOLO(w), root, "val", imgsz)
    print("VAL", json.dumps(val), flush=True)
    conf = {k: v["conf"] for k, v in val.items()}
    test = T._sweep(YOLO(w), root, "test", imgsz, conf_by_cls=conf)
    print("TEST", json.dumps(test), flush=True)
    private = T._private(YOLO(w), imgsz, conf, f"/ds/runs/{run}/private_viz")
    print("PRIVATE", json.dumps(private), flush=True)
    with open(f"{root}/data.yaml", "w") as f:
        f.write(f"path: {root}\nval: images/val\ntest: images/test\ntrain: images/val\nnames:\n  0: door\n  1: window\n  2: fixture\n")
    m = YOLO(w).val(data=f"{root}/data.yaml", split="test", imgsz=imgsz, batch=16, plots=False, verbose=False)
    res = {"run": run, "data": data, "val": val, "conf": conf, "test": test,
           "test_map50": round(float(m.box.map50), 4), "test_map50_95": round(float(m.box.map), 4),
           "test_map50_per_class": {T.CLS[i]: round(float(x), 4) for i, x in enumerate(m.box.ap50)},
           "private": private, "eval_minutes": round((time.time() - t0) / 60, 1),
           "caveat": ("trained on question-referenced (held-out) Swiss drawings; not a held-out accuracy" if run == "y11l"
                      else "trained on question-free Swiss v3 floors only; test = real dataset Swiss PDFs (unseen)")}
    json.dump(res, open(f"/ds/runs/{run}/result.json", "w"), indent=1)
    vol.commit()
    print("RESULT", json.dumps(res), flush=True)
    return res


@app.local_entrypoint()
def main(run: str = "y11l", data: str = "yolo"):
    print(evaluate.remote(run, data))
