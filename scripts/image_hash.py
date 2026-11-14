"""Print the local source fingerprint used by deploy/Dockerfile (no Git required)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.image_info import code_hash  # noqa: E402


if __name__ == "__main__":
    print(code_hash(ROOT))
