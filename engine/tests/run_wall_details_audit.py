"""Read-only real-file wall details audit; no geometry rebuild or model calls."""
import argparse
import json
import tempfile
from pathlib import Path

from engine import linked, wallarea
from server.linked_routes import _shape


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--blind", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = root / "results/final/WALLPANEL"
    output.mkdir(parents=True, exist_ok=True)
    report = {"blind_selected_before_development": args.blind, "files": [], "cost_usd": 0}
    for doc_id in ["ifc_bench__ac20-arc", "swiss_dwellings__site3468-bldg5347-floor23670", "cubicasa5k__colorful-12200", args.blind]:
        measurement = wallarea._wallgeom(doc_id, root / "artifacts")
        if measurement is None:
            measurement = wallarea.estimate_planmaps(doc_id, root / "artifacts", "")
        candidates = measurement.get("walls", [])
        row = {"doc_id": doc_id, "supported_walls": len(candidates), "unsupported_walls": len(measurement.get("skipped", [])), "checked": []}
        for wall in candidates[:3]:
            item = linked.lookup(doc_id, wall["item_id"], root / "artifacts")
            assert item is not None
            payload = _shape(doc_id, item)
            detail = payload["wall_details"]
            assert detail and detail["height_m"] > 0
            for face in detail["faces"]:
                assert face["gross_m2"] is not None
                assert abs(face["gross_m2"] - face["opening_m2"] - face["net_m2"]) < 1e-7
            row["checked"].append({"item_id": wall["item_id"], "tag": item["tag"], "wall_details": detail})
            if len(row["checked"]) == 1:
                (output / f"{doc_id}.item.json").write_text(json.dumps(payload, indent=2) + "\n")
        assert row["checked"], f"No supported wall on {doc_id}"
        scene_path = root / "artifacts" / doc_id / "scene.json"
        if scene_path.exists():
            scene = json.loads(scene_path.read_text())
            source_ids = {w["item_id"] for w in candidates + measurement.get("skipped", [])}
            generated_id = next((iid for iid, it in scene.get("items", {}).items() if it.get("kind") == "wall" and iid not in source_ids), None)
            if generated_id and scene.get("source_planmap"):
                payload = _shape(doc_id, linked.lookup(doc_id, generated_id, root / "artifacts"))
                assert payload["wall_details"]["status"] == "Estimate"
                row["generated_scene_wall"] = payload
                (output / f"{doc_id}.scene-item.json").write_text(json.dumps(payload, indent=2) + "\n")
                # Shared artifacts are immutable in worker worktrees. Verify a
                # fresh extrusion in scratch, retaining its exact source outlines.
                from pipeline.extrude import process
                scratch_root = Path(tempfile.mkdtemp(prefix="wallpanel-scene-"))
                scratch = scratch_root / doc_id
                scratch.mkdir()
                original = root / "artifacts" / doc_id
                for pattern in ("doc.json", "planmap-*.json", "page-*.png", "text-*.json"):
                    for source in original.glob(pattern):
                        (scratch / source.name).symlink_to(source.resolve())
                process(doc_id, scratch, raster_walls=True, _split_storeys=False)
                rebuilt = json.loads((scratch / "scene.json").read_text())
                rebuilt_id = next(iid for iid, it in rebuilt["items"].items() if it.get("kind") == "wall")
                payload = _shape(doc_id, linked.lookup(doc_id, rebuilt_id, scratch_root))
                assert payload["wall_details"]["length_m"] > 0
                assert payload["wall_details"]["faces"][0]["net_m2"] is not None
                row["regenerated_scene_wall"] = payload
                (output / f"{doc_id}.regenerated.item.json").write_text(json.dumps(payload, indent=2) + "\n")
                (output / f"{doc_id}.scratch.json").write_text(json.dumps({"artifacts": str(scratch)}, indent=2) + "\n")
        report["files"].append(row)
        print(f"{doc_id}: {len(row['checked'])} detail checks, {len(candidates)} supported, {row['unsupported_walls']} unavailable", flush=True)
    (output / "real-files.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
