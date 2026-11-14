"""F-MEP: re-extract piping.json + mep.json for every MEP-like IFC in artifacts/; write results/final/MEP/units_before_after.json."""
import json, re, sys
from collections import Counter
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine import mep
from vision import piping

def summ(path):
    if not path.exists():
        return None
    d = json.loads(path.read_text())
    pipes = d.get("pipes") or d.get("segments") or []
    dn = [p.get("dn_mm") for p in pipes]
    got = [x for x in dn if x]
    bad = [x for x in got if x < 6 or x > 1500]
    return {"n": len(pipes), "with_size": len(got), "implausible": len(bad), "min": min(got) if got else None, "max": max(got) if got else None,
            "most_common": Counter(round(x, 3) for x in got).most_common(4), "total_length_m": round(sum(p.get("length_m") or 0 for p in pipes), 2)}

PAT = re.compile(r"plumb|mep|hvac|electr|heating|ventil|sanit|pipe|water|fire|sprink", re.I)
out = {}
for ad in sorted((ROOT / "artifacts").iterdir()):
    if not ad.is_dir() or ad.name.startswith("opening_design") or not (PAT.search(ad.name) or (ad / "piping.json").exists()):
        continue
    ifc = mep._find_ifc(ad.name)
    if ifc is None:
        continue
    before = summ(ad / "piping.json")
    try:
        res = piping.extract(ad.name, ifc, ad / "elements.json")
        (ad / "piping.json.tmp").write_text(json.dumps(res)); (ad / "piping.json.tmp").replace(ad / "piping.json")
        m = mep.write(ad.name, ifc, ad)
        out[ad.name] = {"before": before, "after": summ(ad / "piping.json"), "services": len(m["services"]), "structure": len(m["structure"])}
        print(ad.name, out[ad.name]["before"] and out[ad.name]["before"]["most_common"][:2], "->", out[ad.name]["after"]["most_common"][:2], out[ad.name]["services"], flush=True)
    except Exception as e:  # noqa: BLE001
        out[ad.name] = {"error": str(e)[:200]}; print(ad.name, "ERR", e, flush=True)
(ROOT / "results/final/MEP/units_before_after.json").write_text(json.dumps(out, indent=1))
