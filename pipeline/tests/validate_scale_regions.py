"""Read-only real-file validation. Run via scripts/heavy.sh (local OCR).

Source files and shared artifacts are never modified. This evaluates scale
metadata, not room detection or end-to-end answer accuracy.
"""
import argparse
import json
import tempfile
from pathlib import Path

from PIL import Image

from engine.reader.text import ocr_words
from engine.scales import scale_anchors
from pipeline.scale_regions import annotate_planmap, dxf_regions


def raster(path):
    with tempfile.TemporaryDirectory(prefix="f-scales-") as tmp:
        image = Image.open(path)
        dpi = image.info.get("dpi")
        width, height = image.size
        dest = Path(tmp) / "page.png"
        image.save(dest)
        words = ocr_words(dest)
        pm = {"doc_id": path.stem, "page": 1, "image": {"w": width, "h": height},
              "scale": {"m_per_px": None, "method": "none", "confidence": 0}, "items": []}
        pm = annotate_planmap(pm, words, image, dpi=dpi[0] if dpi else None)
        return {"file": str(path), "origin": path.parent.name, "format": path.suffix,
                "image": [width, height], "dpi": dpi, "ocr_words": len(words),
                "anchors": scale_anchors(words), "regions": pm.get("regions", []), "main_scale": pm["scale"],
                "status": "processed; no crash", "measurement_accuracy": "not evaluated; no annotated measurement ground truth"}


def dxf(path):
    import ezdxf

    from pipeline.pages import dxf_frame, dxf_lines
    doc = ezdxf.readfile(path)
    x0, y0, a, w, h = dxf_frame(dxf_lines(doc))
    tf = {"a": a, "bx": 20-x0*a, "by": h-20+y0*a}
    papers = []
    for layout in doc.layouts:
        if layout.name != "Model":
            papers.extend(dxf_regions(doc, {"a": 1, "bx": 0, "by": 0}, layout))
    return {"file": str(path), "origin": path.parent.name, "format": ".dxf", "units_code": doc.units,
            "image": [w, h], "modelspace_regions": dxf_regions(doc, tf), "paperspace_regions": papers,
            "status": "processed; no crash", "measurement_accuracy": "not evaluated; no annotated measurement ground truth"}


def planmap(path):
    """Real stored maps with a generated single-view wrapper: regression only."""
    import copy

    from engine.scales import apply_item_scales
    from engine.solvers.data import Item
    raw = path.read_bytes()
    pm = json.loads(raw)
    width, height = pm["image"]["w"], pm["image"]["h"]
    pm["regions"] = [{"bbox": [0, 0, width, height], "title": "generated for demo regression", "scale": dict(pm["scale"])}]
    items = []
    for x in pm["items"]:
        props = copy.deepcopy(x.get("props") or {})
        q = {k: props[k] for k in ("area_m2", "width_m", "height_m", "length_m") if props.get(k) is not None}
        if props.get("area_m2_label") is not None:
            q["area_m2"] = props["area_m2_label"]
        items.append(Item(x["item_id"], x["kind"], bbox_px=x.get("bbox_px"), polygon_px=x.get("polygon_px"),
                          props=props, q=q, source=x.get("source", "")))
    before = [dict(i.q) for i in items]
    apply_item_scales(items, pm)
    unchanged = sum(all(it.q.get(k) == value for k, value in old.items()) for it, old in zip(items, before))
    assert path.read_bytes() == raw
    assert unchanged == len(items)
    return {"file": str(path), "source": "real stored plan map; generated single-view wrapper for regression only",
            "items": len(items), "items_with_stored_quantities_preserved": unchanged, "source_bytes_unchanged": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--planmaps", nargs="*", type=Path, default=[])
    args = parser.parse_args()
    rows = []
    for path in args.files:
        row = dxf(path) if path.suffix.lower() == ".dxf" else raster(path)
        rows.append(row)
        print(json.dumps({"file": str(path), "status": row["status"], "anchors": len(row.get("anchors", [])),
                          "regions": len(row.get("regions", row.get("modelspace_regions", [])))}), flush=True)
    for path in args.planmaps:
        row = planmap(path)
        rows.append(row)
        print(json.dumps(row), flush=True)
    args.out.write_text(json.dumps(rows, indent=2))
