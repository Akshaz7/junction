"""Answer-object validation against CONTRACT 5.7."""
import json
from pathlib import Path

import jsonschema

_SCHEMA = json.loads((Path(__file__).parent / "schemas" / "answer.schema.json").read_text())
_VALIDATOR = jsonschema.Draft202012Validator(_SCHEMA)


def validate_answer(obj: dict) -> None:
    """Raises jsonschema.ValidationError if obj is not a contract-valid answer."""
    _VALIDATOR.validate(obj)
