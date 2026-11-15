"""Answer-object validation against CONTRACT 5.7."""
import json
from pathlib import Path

import jsonschema

_SCHEMA = json.loads((Path(__file__).parent / "schemas" / "answer.schema.json").read_text())
ROUTES = tuple(_SCHEMA["properties"]["route"]["enum"])
ROUTE_ALIASES = {"multi": "hybrid", "analytics": "hybrid", "schedule": "index", "printed": "index"}
_VALIDATOR = jsonschema.Draft202012Validator(_SCHEMA)


def validate_answer(obj: dict) -> None:
    """Raises jsonschema.ValidationError if obj is not a contract-valid answer."""
    # Known engine-internal route labels (e.g. "multi") must never crash an answer: map them to the contract's route.
    if isinstance(obj, dict) and obj.get("route") in ROUTE_ALIASES:
        obj["route"] = ROUTE_ALIASES[obj["route"]]
    _VALIDATOR.validate(obj)
