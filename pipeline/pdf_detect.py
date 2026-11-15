"""EXPERIMENT: detector supplement for the vector plan map. OFF unless PDF_DETECT=1 (unset = no call, no change).

DOOR CONFIRM ONLY (agreed after the on/off tests): a vector door item that a detected door overlaps gets
props.det_conf and props.det_evidence ("derived: detector conf X"). Nothing else:
  - no windows / fixtures (the Swiss-trained detector found 0 true windows on the gold sheets),
  - no flags (it flagged true doors), no suggestions (window suggestions were all false),
  - never adds, removes or moves geometry; the IFC is identical with the hook on or off.
The detector output is model-detected evidence (Hologram_Evidence Source "derived"), never a measurement.

The model runs on Modal (experiments/detector/modal/detect.py, app "junction-det"); the call goes through a separate
interpreter (PDF_DETECT_PY) that has the `modal` package. Failures never break the plan map: pm["detector"]["error"].
ultralytics (AGPL-3.0) is used for training/inference on Modal only; not for the product without a licence decision.
"""
from __future__ import annotations

import json
import math
import os
import subprocess

CLIENT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pdf_detect_client.py")


def enabled() -> bool:
    return os.environ.get("PDF_DETECT", "") == "1"


def _timeout_s() -> float:
    """Wall-clock cap for the Modal call (live uploads must not hang on a cold GPU). PDF_DETECT_TIMEOUT_S, default 30."""
    try:
        v = float(os.environ.get("PDF_DETECT_TIMEOUT_S", "30"))
        return v if v > 0 else 30.0
    except ValueError:
        return 30.0


def _call(pdf_path, page_index, m_per_pt, timeout=None):
    timeout = _timeout_s() if timeout is None else timeout
    py = os.environ.get("PDF_DETECT_PY")
    if not py:
        raise RuntimeError("PDF_DETECT_PY not set (interpreter with the modal package)")
    out = subprocess.run([py, CLIENT, str(pdf_path), str(page_index), json.dumps(m_per_pt)], capture_output=True,
                         text=True, timeout=timeout)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[-300:])
    return json.loads(out.stdout.strip().splitlines()[-1])


def _iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    i = ix * iy; u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i
    return i / u if u > 0 else 0.0


def _centre_dist(a, b):
    return math.dist(((a[0] + a[2]) / 2, (a[1] + a[3]) / 2), ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2))


def apply(pm: dict, pdf_path, page_index: int, s_px_per_pt: float, m_per_pt: float | None) -> dict:
    """Adds props.det_conf to confirmed vector doors and a summary in pm["detector"]. Returns the summary."""
    summ = {"enabled": True, "mode": "door-confirm-only"}
    try:
        r = _call(pdf_path, page_index, m_per_pt)
    except Exception as e:  # noqa: BLE001
        summ["error"] = f"{type(e).__name__}: {e}"[:300]
        pm["detector"] = summ
        return summ
    dets = [[v * s_px_per_pt for v in d["bbox_pt"]] + [d["conf"]] for d in r["items"] if d["kind"] == "door"]
    m_per_px = (m_per_pt or 0.0254 / 72 * 100) / s_px_per_pt
    tol = 0.5 / m_per_px  # centres within 0.5 m
    doors = [it for it in pm.get("items", []) if it.get("kind") == "door"]
    pairs = sorted((-_iou(v["bbox_px"], d[:4]), i, j) for i, v in enumerate(doors) for j, d in enumerate(dets)
                   if _iou(v["bbox_px"], d[:4]) >= 0.1 or _centre_dist(v["bbox_px"], d[:4]) <= tol)
    used_v, used_d = set(), set()
    for _, i, j in pairs:
        if i in used_v or j in used_d:
            continue
        used_v.add(i); used_d.add(j)
        p = doors[i].setdefault("props", {})
        p["det_conf"] = round(dets[j][4], 3)
        p["det_evidence"] = f"derived: detector conf {dets[j][4]:.2f}"
    summ.update({k: r.get(k) for k in ("weights", "run", "thresholds", "tiles", "seconds", "scale_assumed")})
    summ.update({"doors_vector": len(doors), "doors_detected": len(dets), "doors_confirmed": len(used_v),
                 "evidence": "model-detected (Hologram_Evidence Source=derived); never measured"})
    pm["detector"] = summ
    return summ
