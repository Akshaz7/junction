"""Build fingerprint shared by the container build and the local comparison script."""
import hashlib
import json
from pathlib import Path

def code_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for folder in ("server", "engine", "pipeline"):
        for path in sorted((root / folder).rglob("*")):
            relative = path.relative_to(root)
            if (not path.is_file() or "__pycache__" in relative.parts
                    or ".pytest_cache" in relative.parts or path.suffix in {".pyc", ".pyo"}):
                continue
            # Include names and fixed-size content digests so renames and file boundaries matter.
            digest.update(relative.as_posix().encode() + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def image_info() -> dict:
    from . import config

    # Never substitute BUILD_REV or a runtime hash for missing build-time evidence.
    try:
        data = json.loads((config.REPO / "IMAGE_INFO.json").read_text())
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    return {key: data.get(key) if isinstance(data.get(key), str) else None
            for key in ("code_hash", "built_at")}


def file_counts() -> dict:
    from . import config

    bench = config.REPO / "results" / "bench"
    artifacts = config.artifacts_dir()
    try:
        bench_files = sum(p.is_file() for p in bench.glob("*.json"))
    except OSError:
        bench_files = None
    try:
        artifacts_docs = sum(p.is_dir() for p in artifacts.iterdir())
    except FileNotFoundError:
        artifacts_docs = 0
    except OSError:
        artifacts_docs = None
    return {"bench_files": bench_files, "artifacts_docs": artifacts_docs}
