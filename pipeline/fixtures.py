import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def load_fixtures(fixtures_path=None, artifacts=None) -> list[dict]:
    """doc.json of every doc_id listed in tests/fixtures.json."""
    ids = json.loads(Path(fixtures_path or REPO / "tests" / "fixtures.json").read_text())
    art = Path(artifacts or REPO / "artifacts")
    return [json.loads((art / i / "doc.json").read_text()) for i in ids]
