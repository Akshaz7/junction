"""D-04: choose the 10 fixture doc_ids (most English questions) -> tests/fixtures.json."""
import json
from collections import Counter
from pathlib import Path

from pipeline.langcheck import is_english
from pipeline.registry import REPO, doc_id_for_question_path

ROOT = REPO / "data" / "junction-dataset-preview"


def main():
    cnt, docs_files = Counter(), {}
    for l in open(ROOT / "questions.jsonl"):
        q = json.loads(l)
        if is_english(q["question"]):
            d = doc_id_for_question_path(q["path"])
            cnt[d] += 1
    reg = {json.loads(l)["doc_id"]: json.loads(l) for l in open(REPO / "artifacts" / "registry.jsonl")}

    def top(pred, n):
        c = sorted((d for d in cnt if d in reg and pred(reg[d])), key=lambda d: (-cnt[d], d))
        return c[:n]

    cub = ["cubicasa5k__colorful-11397"]
    cub += top(lambda r: r["source"] == "cubicasa5k" and r["doc_id"].startswith("cubicasa5k__high-quality-") and "architectural" not in r["doc_id"], 1)
    cub += [d for d in top(lambda r: r["doc_id"].startswith("cubicasa5k__high-quality-architectural"), 4) if d not in cub][:4 - len(cub)]
    swiss = top(lambda r: r["source"] == "swiss_dwellings" and {"pdf", "dxf", "png"} <= set(r["formats"]), 3)
    ids = cub + swiss + ["ifc_bench__ac20-arc", "ifc_bench__digital-hub-arc"] + \
        top(lambda r: r["source"] == "ifc_models" and "pdf" in r["formats"], 1)
    assert len(ids) == 10 and len(set(ids)) == 10 and all(i in reg for i in ids), ids
    (REPO / "tests" / "fixtures.json").write_text(json.dumps(ids, indent=1) + "\n")
    print(ids)


if __name__ == "__main__":
    main()
