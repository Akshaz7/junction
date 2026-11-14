"""D-15: sample project documents for the ac20 demo building. Every file starts with the label
"GENERATED FOR DEMO". Door data and counts come from elements.json; nothing else is quantified.
Output: artifacts/samples/ac20-*.md|csv.   CLI: python -m pipeline.samples"""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOC = "ifc_bench__ac20-arc"
LABEL = "GENERATED FOR DEMO: fictional project document written for the Hologram demo. Not a real contract document."


def main():
    art = REPO / "artifacts"
    out = art / "samples"
    out.mkdir(exist_ok=True)
    d = json.loads((art / DOC / "elements.json").read_text())
    els = d["elements"]
    kinds = Counter(e["kind"] for e in els)
    storeys = [s["name"] for s in sorted(d["storeys"], key=lambda s: s["elevation_m"])]
    doors = sorted((e for e in els if e["kind"] == "door"),
                   key=lambda e: (next((s["elevation_m"] for s in d["storeys"] if s["name"] == (e["storey"] or {}).get("name")), 0), e["name"]))
    by_level = Counter((e["storey"] or {}).get("name", "?") for e in doors)
    ext = sum(1 for e in els if e["kind"] == "wall" and e["props"].get("is_external"))

    # door schedule (real data)
    rows = []
    for e in doors:
        q = e["quantities"]
        rows.append({"mark": e["name"], "level": (e["storey"] or {}).get("name", ""), "type": e["type_name"] or "",
                     "width_m": q.get("width_m", ""), "height_m": q.get("height_m", ""),
                     "area_m2": q.get("area_m2", ""), "material": e["props"].get("material", "not in model"),
                     "fire_rating": e["props"].get("fire_rating", "not in model"), "item_id": e["item_id"]})
    with open(out / "ac20-door-schedule.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    md = [LABEL, "", "# Door schedule, AC20 building", "",
          f"Source: door data read from the IFC model ({len(doors)} doors). Cells say \"not in model\" where the model has no value.", "",
          "| Mark | Level | Type | Width m | Height m | Area m2 | Material | Fire rating | Item id |", "|---|---|---|---|---|---|---|---|---|"]
    md += [f"| {r['mark']} | {r['level']} | {r['type']} | {r['width_m']} | {r['height_m']} | {r['area_m2']} | {r['material']} | {r['fire_rating']} | {r['item_id']} |" for r in rows]
    md += ["", "Doors per level: " + ", ".join(f"{k} {v}" for k, v in sorted(by_level.items(), key=lambda kv: storeys.index(kv[0]) if kv[0] in storeys else 99)) + "."]
    (out / "ac20-door-schedule.md").write_text("\n".join(md) + "\n")

    # specification (counts from the model, no invented requirements)
    spec = [LABEL, "", "# Short specification, AC20 building", "",
            "## 1. Scope", "This sheet describes the architectural model of the AC20 building as it is modelled. "
            "It lists what the model contains. It sets no performance requirements; where the model has no value, the answer is \"not in model\".", "",
            "## 2. Levels", "The model has %d levels: %s." % (len(storeys), ", ".join(storeys)), "",
            "## 3. Model content",
            "| Element | Count |", "|---|---|"] + [f"| {k} | {v} |" for k, v in kinds.most_common()] + ["",
            "## 4. Doors", f"The model has {len(doors)} doors. Types in the model: " +
            "; ".join(f"{t} ({n})" for t, n in Counter(e["type_name"] for e in doors).most_common()) +
            ". See the door schedule for each door.", "",
            "## 5. Gaps in the model data",
            "Fire rating is not set on any door. External-wall flags are set on %d of %d walls." % (ext, kinds["wall"]), "",
            "## 6. Use", "Answers about this building cite the model element ids shown in the schedule."]
    (out / "ac20-specification.md").write_text("\n".join(spec) + "\n")

    # three meeting minutes (fictional narrative, roles not names, only model-derived figures)
    mins = [
        ("1", "Design coordination", f"Review of the door schedule. The model lists {len(doors)} doors. Open points: fire rating is not set on any door in the model; the architect to confirm which doors need a rating and add it.",
         ["Architect to add fire rating to doors that need one.", "Coordinator to re-export the model after the update."]),
        ("2", "Level review", f"Walk through the {len(storeys)} levels ({', '.join(storeys)}). Doors per level in the model: " + ", ".join(f"{k} {v}" for k, v in by_level.items()) + ". The group agreed to check door widths on the lowest level first.",
         ["Site lead to list doors on the lowest level that are narrower than the others.", "Architect to mark them on the plan."]),
        ("3", "Handover preparation", "Agreed that the door schedule and the model are the reference for the handover pack. Questions from the client are answered from the model with element ids so each answer can be checked on the drawing.",
         ["Coordinator to publish the schedule with the pack.", "Client representative to send any further questions in writing."]),
    ]
    for n, title, body, acts in mins:
        t = [LABEL, "", f"# Meeting minutes {n}: {title}, AC20 building", "",
             "Attendees (roles): architect, coordinator, site lead, client representative.", "", "## Discussion", body, "", "## Actions"]
        t += [f"- {a}" for a in acts]
        (out / f"ac20-minutes-{n}.md").write_text("\n".join(t) + "\n")
    print(sorted(p.name for p in out.iterdir()))


if __name__ == "__main__":
    main()
