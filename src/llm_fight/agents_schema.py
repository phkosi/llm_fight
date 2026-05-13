"""Provider schema adaptation for chat requests."""

from __future__ import annotations

from typing import Any

from .engine import constants as C


def response_format(schema: dict[str, Any]) -> dict[str, Any]:
    return {
        C.SCHEMA_TYPE: "json_schema",
        "json_schema": {
            C.NAME: "llm_fight_response",
            "schema": schema,
        },
    }


UNSUPPORTED_OLLAMA_SCHEMA_KEYS = {
    "allOf",
    "anyOf",
    "oneOf",
    "not",
    "if",
    "then",
    "else",
    "const",
    C.SCHEMA_PATTERN,
    C.SCHEMA_MINIMUM,
    C.SCHEMA_MAXIMUM,
    C.SCHEMA_MIN_PROPERTIES,
    C.SCHEMA_MAX_PROPERTIES,
}


def schema_for_ollama(schema: Any) -> Any:
    """Return a JSON Schema subset that Ollama's grammar compiler accepts."""

    if isinstance(schema, list):
        return [schema_for_ollama(item) for item in schema]
    if not isinstance(schema, dict):
        return schema

    result: dict[str, Any] = {}
    for key, value in schema.items():
        if key in UNSUPPORTED_OLLAMA_SCHEMA_KEYS:
            continue
        if key == C.SCHEMA_PATTERN_PROPERTIES:
            properties = result.setdefault(C.SCHEMA_PROPERTIES, {})
            for pattern, subschema in value.items():
                if pattern == f"^[{C.FIGHTER_A}{C.FIGHTER_B}]$":
                    properties[C.FIGHTER_A] = schema_for_ollama(subschema)
                    properties[C.FIGHTER_B] = schema_for_ollama(subschema)
            continue
        result[key] = schema_for_ollama(value)
    return result
