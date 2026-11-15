"""Frozen demo wording checks; source truth is read before changing answer code.

Run through scripts/heavy.sh with MODELS_FAKE=1 and PYTHONPATH=.
prepare freezes 15 AC20 + 10 FZK questions from indexed graph facts, without
calling the answer implementation. before/after evaluate identical questions.
These verify graph reasoning over source indexes, not independent PDF accuracy.
"""
import argparse
import json
import time
from collections import defaultdict
from pathlib import Path

from engine.kg.build import build_uncached
from engine.projects.roles import level_ordinal

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent


def write(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def projects():
    # Use the seeded demo projects' documents, including their existing sheets.
    for folder in sorted((ROOT / "artifacts/projects").iterdir()):
        caches = list(folder.glob("kg-*.json"))
        if not caches:
            continue
        raw = json.loads(max(caches, key=lambda p: p.stat().st_mtime).read_text())
        g = raw.get("graph", raw)
        docs = [n for n in g["nodes"] if n["kind"] == "doc"]
        family = "AC20" if any("ifc_bench__ac20-arc" in n["doc_ids"] for n in docs) else "FZK"
        yield family, {"id": folder.name, "docs": [{"doc_id": d} for n in docs for d in n["doc_ids"]]}


def prepare():
    sets = []
    for family, project in projects():
        g = build_uncached(project, ROOT / "artifacts")
        counts = defaultdict(lambda: defaultdict(int))
        for n in g["nodes"]:
            if n["kind"] == "door":
                for d in n["doc_ids"]:
                    counts[d][str(n.get("level"))] += 1
        # Both models and their existing plan-map sheets have the same count on
        # each corresponding level. Keep the actual counted values as truth.
        truth_counts = dict(counts)
        all_levels = defaultdict(set)
        for levels in counts.values():
            for level, value in levels.items():
                all_levels[level_ordinal(level)].add(value)
        assert all(len(values) == 1 for values in all_levels.values()), truth_counts
        questions = []
        wordings = [
            "Do the plan and model agree on doors on Erdgeschoss?",
            "Does the plan match the model on doors on the ground floor?",
            "Compare doors per floor across files.",
            "Which files disagree?",
            "Do the drawings agree on doors on EG?",
            "Do the plan and model agree on doors on level 0?",
        ]
        if family == "AC20":
            wordings += ["Does the plan match the model?",
                         "Compare doors across files on 1. Obergeschoss.",
                         "Do the model and plan agree on doors on the first floor?"]
        for q in wordings:
            questions.append({"question": q, "expect": {"shape": "agreement", "value": 100.0},
                              "truth": "Equal source-index door counts per matching floor; existing comparison edges all agree.",
                              "source_counts": truth_counts})
        tag = "Tür-019" if family == "AC20" else "Innentuer-1"
        found = [n for n in g["nodes"] if n["kind"] == "door" and n["label"] == tag]
        parent = {n["id"]: n["id"] for n in found}
        def find(x):
            while parent[x] != x:
                x = parent[x]
            return x
        for e in g["edges"]:
            if e["kind"] == "same_as" and e["from"] in parent and e["to"] in parent:
                parent[find(e["from"])] = find(e["to"])
        groups = len({find(n["id"]) for n in found})
        appearance_qs = [f"Where else does door {tag} appear?", f"Which other files show door {tag}?"]
        if family == "AC20":
            appearance_qs += [f"Where else does door {tag} appear on the ground floor?"]
        for q in appearance_qs:
            selected = [n for n in found if "ground floor" not in q or level_ordinal(n.get("level")) == 0]
            questions.append({"question": q, "expect": {"shape": "appearances", "groups": groups if len(selected) == len(found) else 1,
                              "required_nodes": sorted(n["id"] for n in selected)},
                              "truth": "Exact label source records grouped by explicit same_as links; distinct floors remain separate."})
        label = "Flur EG Eingang" if family == "AC20" else "Flur"
        rooms = [n for n in g["nodes"] if n["kind"] == "room" and n["label"] == label]
        dependencies = {e["from"] for e in g["edges"] if e["kind"] in ("bounds", "in_room", "serves") and e["to"] in {n["id"] for n in rooms}}
        assert dependencies, label
        impact_qs = (["If the ceiling in the entrance hall drops to 2.4 m what is affected?",
                      "If the ceiling in room Flur EG Eingang drops to 2400 mm what is affected?",
                      "If the ceiling in the entrance hall is lowered to 240 cm, what is affected?"] if family == "AC20" else
                     ["If the ceiling in the hall drops to 2.4 m what is affected?",
                      "If the ceiling in room Flur drops to 2400 mm what is affected?"])
        for q in impact_qs:
            questions.append({"question": q, "expect": {"shape": "impact", "required_nodes": sorted(dependencies),
                              "origin_nodes": [n["id"] for n in rooms], "ceiling_height_m": 2.4},
                              "truth": "Explicit room boundaries/containment/service graph edges; English room usage translated via general vocabulary."})
        assert len(questions) == (15 if family == "AC20" else 10)
        sets.append({"family": family, "project": project, "questions": questions})
    write("round2-questions.json", sets)
    print("Frozen", [(s["family"], len(s["questions"])) for s in sets])


def evaluate(mode):
    from engine.kg_answer import answer
    import jsonschema
    schema = json.loads((ROOT / "server/schemas/answer.schema.json").read_text())
    reports = []
    for case_set in json.loads((OUT / "round2-questions.json").read_text()):
        project = case_set["project"]
        start = time.perf_counter()
        if mode == "cached":
            caches = list((ROOT / "artifacts/projects" / project["id"]).glob("kg-*.json"))
            raw = json.loads(max(caches, key=lambda p: p.stat().st_mtime).read_text())
            g = raw.get("graph", raw)
        else:
            g = build_uncached(project, ROOT / "artifacts")
        build_s = time.perf_counter() - start
        rows = []
        for case in case_set["questions"]:
            start = time.perf_counter()
            result = answer(case["question"], project, ROOT / "artifacts", graph=g)
            error = None
            try:
                assert result is not None, "Question was not routed to graph answers"
                jsonschema.validate(result, schema)
                data, exp = result["graph_answer"], case["expect"]
                assert data["shape"] == exp["shape"], result["answer"]["text_md"]
                if "value" in exp:
                    assert result["answer"]["value"] == exp["value"]
                if "groups" in exp:
                    assert len(data.get("groups", [{"origin": data.get("origin")}])) == exp["groups"]
                sourced = {e["node"]["id"] for e in data.get("items", [])}
                sourced.update(x["origin"] for x in data.get("groups", []))
                if data.get("origin"):
                    sourced.add(data["origin"])
                assert set(exp.get("required_nodes", [])) <= sourced, "Missing source records: " + str(set(exp.get("required_nodes", [])) - sourced)
                if "origin_nodes" in exp:
                    assert data["origin"] in exp["origin_nodes"]
                    assert data["change"]["value"] == exp["ceiling_height_m"]
                path = result["reasoning"]["graph_path"]
                assert path and result["citations"]
                assert result["answer"]["confidence"] == min(e["confidence"] for e in path)
                assert result["cost"] == {"usd_total": 0, "calls": []}
                assert all(e["from_id"] and e["to_id"] for e in path)
            except (AssertionError, jsonschema.ValidationError) as exc:
                error = str(exc)
            rows.append({"question": case["question"], "pass": error is None, "error": error,
                         "shape": result["graph_answer"]["shape"] if result else None,
                         "value": result["answer"]["value"] if result else None,
                         "answer": result["answer"]["text_md"] if result else None,
                         "citations": len(result["citations"]) if result else 0,
                         "graph_path_edges": len(result["reasoning"]["graph_path"]) if result else 0,
                         "elapsed_s": round(time.perf_counter()-start, 4)})
        report = {"family": case_set["family"], "build_s": round(build_s, 3),
                  "passed": sum(x["pass"] for x in rows), "total": len(rows), "questions": rows}
        reports.append(report)
        print(report["family"], report["passed"], "/", report["total"], "build", report["build_s"])
        for r in rows:
            if not r["pass"]:
                print("FAIL", r["question"], r["error"])
    write("round2-" + mode + ".json", reports)


if __name__ == "__main__":
    mode = argparse.ArgumentParser()
    mode.add_argument("mode", choices=["prepare", "before", "after", "cached"])
    args = mode.parse_args()
    prepare() if args.mode == "prepare" else evaluate(args.mode)
