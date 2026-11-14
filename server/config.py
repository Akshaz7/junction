"""Environment config. Local defaults work with `make dev` and no keys."""
import os

from dotenv import find_dotenv, dotenv_values

# Load .env for server settings only. Provider keys (API keys, tokens) stay out of os.environ:
# engine.models reads .env itself, and leaking them here made engine tests see real keys.
_SECRET = ("KEY", "TOKEN", "SECRET")
for _k, _v in dotenv_values(find_dotenv(usecwd=True)).items():
    if _v is not None and _k not in os.environ and not any(t in _k.upper() for t in _SECRET):
        os.environ[_k] = _v

DEFAULT_DATABASE_URL = "postgresql://hologram:hologram@localhost:5433/hologram"


def database_url() -> str:
    # .env may carry an empty placeholder (DATABASE_URL=): treat empty as unset
    return os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL


def rate_limit_enabled() -> bool:
    return os.environ.get("RATE_LIMIT", "0") == "1"


REPO = __import__("pathlib").Path(__file__).resolve().parent.parent


def artifacts_dir():
    from pathlib import Path
    return Path(os.environ.get("ARTIFACTS_DIR") or REPO / "artifacts")


def results_dir():
    from pathlib import Path
    return Path(os.environ.get("RESULTS_DIR") or REPO / "results")
