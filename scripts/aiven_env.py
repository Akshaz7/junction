"""Rebuild the Aiven app env from .env + hologram-pg (never round-trip masked secrets). Usage: python scripts/aiven_env.py <build_rev>"""
import json, subprocess, sys
from dotenv import dotenv_values
env = dotenv_values(".env")
pg = json.loads(subprocess.run(["avn", "service", "get", "hologram-pg", "--json"], capture_output=True, text=True).stdout)
vals = {"RATE_LIMIT": "1", "BUILD_REV": sys.argv[1], "DATABASE_URL": pg.get("service_uri") or "",
        **{k: env.get(k) or "" for k in ("RUNWARE_API_KEY", "NVIDIA_API_KEY", "ELEVENLABS_API_KEY")}}
missing = [k for k, v in vals.items() if not v]
if missing: sys.exit(f"missing: {missing}")
ev = [{"key": k, "value": v, "kind": "variable" if k in ("RATE_LIMIT", "BUILD_REV") else "secret"} for k, v in vals.items()]
r = subprocess.run(["avn", "service", "update", "hologram-api", "-c", "application.environment_variables=" + json.dumps(ev)],
                   capture_output=True, text=True)
print("exit", r.returncode)
