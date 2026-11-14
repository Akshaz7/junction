# Vercel Python entry (LEAD 09:05 fallback host until the Aiven GitHub App exists). Same app as deploy/Dockerfile.
import os, sys
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.environ.setdefault("ARTIFACTS_DIR", os.path.join(ROOT, "artifacts"))
os.environ.setdefault("RATE_LIMIT", "1")
# Vercel functions can only write to /tmp: model cache and cost log go there.
os.environ.setdefault("MODELS_CACHE_DIR", "/tmp/hologram/models-cache")
os.environ.setdefault("MODELS_COSTS_LOG", "/tmp/hologram/costs.jsonl")
from server.app import app  # noqa: E402,F401
