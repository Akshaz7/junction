# Vercel Python entry (LEAD 09:05 fallback host until the Aiven GitHub App exists). Same app as deploy/Dockerfile.
import os, sys
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.environ.setdefault("ARTIFACTS_DIR", os.path.join(ROOT, "artifacts"))
os.environ.setdefault("RATE_LIMIT", "1")
from server.app import app  # noqa: E402,F401
