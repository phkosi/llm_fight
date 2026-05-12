"""Compact, prompt-safe fighter state summaries."""

from __future__ import annotations

import json
from typing import Any

from . import constants as C

_INTACT = "intact"


def _status_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _to_mapping(state: Any) -> dict[str, Any]:
    if hasattr(state, "to_json") and callable(state.to_json):
        return state.to_json()
    if isinstance(state, dict):
        return state
    return {}


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _clean_dict(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value not in (None, "", [])}


def _summarize_effect(effect: Any, effect_type: str) -> dict[str, Any] | None:
    name = _get(effect, C.NAME)
    if not name:
        return None

    metadata = _get(effect, C.METADATA, {}) or {}
    target = metadata.get(C.TARGETED_PART) if isinstance(metadata, dict) else None
    magnitude = _get(effect, "magnitude", _get(effect, C.VALUE))

    return _clean_dict(
        {
            C.TYPE: effect_type,
            C.NAME: name,
            C.EFFECT_TTL: _get(effect, C.EFFECT_TTL),
            "magnitude": magnitude,
            C.TARGETED_PART: target,
            C.EFFECT_MECHANICS: _get(effect, C.EFFECT_MECHANICS, []),
            C.EFFECT_TAGS: _get(effect, C.EFFECT_TAGS, []),
        }
    )


def _active_effects(state: dict[str, Any]) -> list[dict[str, Any]]:
    effects: list[dict[str, Any]] = []
    for effect_type in (C.BUFFS, C.DEBUFFS):
        for effect in state.get(effect_type, []) or []:
            summary = _summarize_effect(effect, effect_type)
            if summary is not None:
                effects.append(summary)
    return effects


def _target_parts(parts: dict[str, Any]) -> list[dict[str, Any]]:
    summaries = []
    for part_id, part in sorted(parts.items()):
        summaries.append(
            _clean_dict(
                {
                    "id": part_id,
                    C.NAME: _get(part, C.NAME, part_id),
                    "vital": bool(_get(part, "is_vital", False)),
                    "severable": bool(_get(part, "can_be_severed", False)),
                    C.BLEED_RATE: int(_get(part, C.BLEED_RATE, 0) or 0),
                    C.BURN_RATE: int(_get(part, C.BURN_RATE, 0) or 0),
                    C.CONSEQUENCE_TAGS: _get(part, C.CONSEQUENCE_TAGS, []),
                    C.CONSEQUENCE_GROUP: _get(part, C.CONSEQUENCE_GROUP),
                }
            )
        )
    return summaries


def _damaged_parts(parts: dict[str, Any]) -> dict[str, Any]:
    damaged = {}
    for name, part in sorted(parts.items()):
        status = _get(part, C.STATUS, _INTACT)
        severed = bool(_get(part, "severed", False))
        layers = _get(part, "layers", []) or []
        damaged_layers = []
        for layer in layers:
            max_hp = _get(layer, C.MAX_HP, 0) or 0
            current_hp = _get(layer, C.CURRENT_HP, max_hp)
            if current_hp is None:
                current_hp = max_hp
            if current_hp < max_hp:
                damaged_layers.append(
                    {
                        C.NAME: _get(layer, C.NAME),
                        C.CURRENT_HP: current_hp,
                        C.MAX_HP: max_hp,
                    }
                )
        if status != _INTACT or severed or damaged_layers:
            damaged[name] = {
                C.STATUS: status,
                "severed": severed,
                "damaged_layers": damaged_layers,
            }
    return damaged


def compact_fighter_state_summary(state: Any) -> dict[str, Any]:
    """Return a compact prompt-safe summary for fighters and Judge Phase 1."""
    data = _to_mapping(state)
    parts = data.get("parts", {}) or {}
    return {
        "id": data.get("id"),
        "class": data.get("class_") or data.get("class"),
        C.LOADOUT: data.get(C.LOADOUT),
        "environment": data.get("environment"),
        C.STATUS: _status_value(data.get(C.STATUS)),
        C.PAIN: data.get(C.PAIN),
        C.EXHAUSTION: data.get(C.EXHAUSTION),
        C.HEAT: data.get(C.HEAT),
        C.ACTIVE_EFFECTS: _active_effects(data),
        C.VALID_TARGET_PARTS: sorted(parts.keys()),
        C.TARGET_PARTS: _target_parts(parts),
        C.DAMAGED_PARTS: _damaged_parts(parts),
    }


def render_fighter_state_summary(summary: Any) -> str:
    """Render a compact summary as stable JSON for prompt inclusion."""
    return json.dumps(summary, sort_keys=True, separators=(",", ":"))


def environment_scope_guardrail() -> str:
    """Prompt guardrail that allows configured features without inventing new ones."""
    return (
        "Use only features present in the current environment, equipment, active effects, "
        "durable state summaries, or created by your current action. Do not claim new cover, "
        "walls, pillars, smoke, shadows, terrain, or objects already exist unless listed there."
    )
