"""Environment config. Local defaults work with `make dev` and no keys."""
import os

from dotenv import load_dotenv

load_dotenv()

DEFAULT_DATABASE_URL = "postgresql://hologram:hologram@localhost:5433/hologram"


def database_url() -> str:
    # .env may carry an empty placeholder (DATABASE_URL=): treat empty as unset
    return os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL


def rate_limit_enabled() -> bool:
    return os.environ.get("RATE_LIMIT", "0") == "1"
