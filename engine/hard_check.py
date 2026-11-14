"""E-59: local grader for the 30 FIX-13 hard cases (results/hard_cases.jsonl, ids fix13-NN-*).
A case is RIGHT when every `must` regex matches the answer and no `mustnot` does; PARTIAL-OK when the answer is a labelled partial
(confidence <= 0.6) that names what it could not do; CONFIDENTLY WRONG when confidence >= 0.8 and it is not right.
Expected values are checked against the model data by hand (AC20 IFC, colorful-11397)."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
P = "Partial answer|not in the document|cannot|not given"
MUST = {
    1: [r"99\.02 m2", r"\*\*76 boxes", r"EUR 2,432"],
    2: [r"Wand-002", r"216\.64 m2", r"302\.94"],
    3: [r"24 tins", r"756\.24"],
    4: [P, r"scale"],
    5: [r"96\.42", r"96\.84", r"EUR 42,614"],
    6: [r"Tür-017", r"Tür-018", r"None of these 2"],
    7: [r"\*\*3 windows", r"5\.40 m2", r"None on 1\. Obergeschoss"],
    8: [r"Oberschmitt", r"24\.75"],
    9: [r"Scope I applied", r"removed volume"],
    10: [P, r"external"],
    11: [r"No laboratory shares a wall"],
    12: [P, r"route"],
    13: [r"neither room shifts", r"0\.00 m"],
    14: [P, r"stair"],
    15: [P, r"compass"],
    16: [P, r"travel distance"], 17: [P, r"fire rating|EI"], 18: [P, r"threshold"], 19: [P, r"scale|dwelling"], 20: [P, r"riser|headroom"],
    21: [r"kylpyhuone", r"WC is not written"],
    22: [r"one combined open space"],
    23: [r"Label as printed", r"model guesses|Model guesses"],
    24: [r"Tür-005 repeats", r"Tuer-016"],
    25: [r"Laboratorys|Laboratories|Laboratory", r"Why not use type_name"],
    26: [r"not in the document"], 27: [r"not in the document"],
    28: [r"cannot say", r"structural engineer"],
    29: [r"not in the document"], 30: [r"not in the document"],
}
MUSTNOT = {n: [r"I couldn't find", r"This is an estimate, not an exact count"] for n in MUST}


def main() -> int:
    os.environ.setdefault("MODELS_FAKE", "1")
    sys.path.insert(0, str(ROOT))
    import engine.answer as A
    rows = [json.loads(l) for l in (ROOT / "results/hard_cases.jsonl").read_text().splitlines() if '"fix13-' in l]
    right = wrong = 0
    for r in rows:
        n = int(re.match(r"fix13-(\d+)", r["id"]).group(1))
        res = A.answer(r["question"], [r["doc_id"]])
        t, conf = res["answer"]["text_md"], res["answer"]["confidence"]
        ok = all(re.search(m, t) for m in MUST[n]) and not any(re.search(m, t) for m in MUSTNOT[n])
        right += ok
        conf_wrong = (not ok) and conf >= 0.8
        wrong += conf_wrong
        print(f"{n:02d} {'RIGHT' if ok else 'MISS '} conf={conf} route={res['route']}{'  CONFIDENTLY WRONG' if conf_wrong else ''}  {r['id']}")
    print(f"right {right}/{len(rows)}  confidently wrong {wrong}")
    return 0 if wrong == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
