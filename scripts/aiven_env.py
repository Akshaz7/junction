"""Rebuild the Aiven app env from .env (DATABASE_URL too: avn's service_uri password is stale/masked) (never round-trip masked secrets). Usage: python scripts/aiven_env.py <build_rev>"""
import json, subprocess, sys
from dotenv import dotenv_values
env = dotenv_values(".env")
vals = {"RATE_LIMIT": "1", "RATE_LIMIT_PER_MIN": "120", "BUILD_REV": sys.argv[1], "PAGES_MAX_SIDE": "6000", "RESTORE_CAP_MB": "400", "DATABASE_URL": env.get("DATABASE_URL") or "",
        **{k: env.get(k) or "" for k in ("RUNWARE_API_KEY", "NVIDIA_API_KEY", "ELEVENLABS_API_KEY")},
        **{k: env[k] for k in ("VERDA_INFERENCE_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY") if env.get(k)}}
missing = [k for k, v in vals.items() if not v]
if missing: sys.exit(f"missing: {missing}")
ev = [{"key": k, "value": v, "kind": "variable" if k in ("RATE_LIMIT", "RATE_LIMIT_PER_MIN", "BUILD_REV") else "secret"} for k, v in vals.items()]
r = subprocess.run(["avn", "service", "update", "hologram-api", "-c", "application.environment_variables=" + json.dumps(ev)],
                   capture_output=True, text=True)
print("exit", r.returncode)
