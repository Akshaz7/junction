"""Compare the merged overlay against a clean main snapshot on shared real data."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
MAIN = subprocess.check_output(["git", "rev-parse", sys.argv[1] if len(sys.argv) > 1 else "origin/main"], cwd=ROOT, text=True).strip()
RUN = """
import json
from pathlib import Path
from engine.bench import load_set, run
r = run(load_set('sample200'), concurrency=2)
Path(__import__('sys').argv[1]).write_text(json.dumps(r, indent=1))
print(json.dumps({'totals': r['totals'], 'numeric': r['cells']['ALL x ALL']}), flush=True)
"""


def bench(folder, name):
    target = OUT / f"rebase-sample200-{name}.json"
    env = {**os.environ, "MODELS_FAKE": "1", "ARTIFACTS_DIR": str(ROOT / "artifacts"), "PYTHONPATH": str(folder)}
    subprocess.run([sys.executable, "-c", RUN, str(target)], cwd=folder, env=env, check=True)
    return json.loads(target.read_text())


with tempfile.TemporaryDirectory(prefix="overlay-main-baseline-") as tmp:
    snapshot = Path(tmp)
    archive = subprocess.check_output(["git", "archive", MAIN, "engine", "pipeline", "server", "models.yaml", "COSTS.md"], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        source.extractall(snapshot, filter="data")
    for name in ("artifacts", "data", "weights"):
        (snapshot / name).symlink_to((ROOT / name).resolve(), target_is_directory=True)
    before = bench(snapshot, "before")
after = bench(ROOT, "after")
key = lambda r: (r["doc_id"], r["question"])
baseline = {key(r): r for r in before["results"]}
regressions = [{"before": baseline[key(r)], "after": r} for r in after["results"]
               if baseline[key(r)]["outcome"] == "correct" and r["outcome"] != "correct"]
report = {"baseline_commit": MAIN, "fake_models": True, "questions_before": len(before["results"]),
          "questions_after": len(after["results"]), "correct_before": before["cells"]["ALL x ALL"]["correct"],
          "correct_after": after["cells"]["ALL x ALL"]["correct"], "correct_to_wrong": len(regressions),
          "regressions": regressions, "cost_usd": before["totals"]["cost_usd"] + after["totals"]["cost_usd"]}
(OUT / "rebase-sample200-comparison.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report), flush=True)
assert report["questions_before"] == report["questions_after"] == 200
assert not regressions
