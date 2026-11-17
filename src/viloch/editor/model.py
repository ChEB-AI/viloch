"""The editor model's JSON schema (``model.schema.json``) and a validator."""

from __future__ import annotations

import functools
import json
import os

SCHEMA_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "model.schema.json"
)


@functools.cache
def schema() -> dict:
    with open(SCHEMA_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def validate(model: dict) -> None:
    """Raise ``jsonschema.ValidationError`` unless ``model`` is a valid editor model
    (needs the ``jsonschema`` package, a dev dependency)."""
    import jsonschema

    jsonschema.validate(model, schema())
