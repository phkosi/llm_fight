"""Effect-payload authorization helpers for Judge Phase 2."""

from __future__ import annotations

import math
from typing import Any, cast

from .engine import constants as C
from .phase2_common import (
    _copy_without_source,
    _is_authorized_consequence,
    _phase2_validation_warning,
)
from .phase2_text import (
    _attempt_allows_self_wound,
    _attempt_self_setup_kind,
    _attempt_targets_opponent,
    _opponent_id,
)
from .state import FighterState


def _effect_payload_warning(
    *,
    fighter_id: str,
    index: int,
    source: Any,
    action: str,
    reason: str,
    field_suffix: str = "",
    canonical_part: str | None = None,
) -> dict[str, Any]:
    return _phase2_validation_warning(
        code=(
            C.WARNING_CODE_CANONICALIZED_EFFECT_TARGET
            if action == "canonicalized"
            else C.WARNING_CODE_INVALID_EFFECT_PAYLOAD
        ),
        fighter_id=fighter_id,
        field=f"delta.{fighter_id}.{C.EFFECTS_ADDED}[{index}]{field_suffix}",
        source=source,
        action=action,
        reason=reason,
        canonical_part=canonical_part,
    )


def _valid_effect_magnitude(effect: dict[str, Any]) -> bool:
    raw_value = effect.get(C.VALUE, effect.get("magnitude"))
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        return False
    value = float(raw_value)
    return math.isfinite(value) and 0 < value <= C.EFFECT_MAX_MAGNITUDE


def _valid_effect_ttl(effect: dict[str, Any]) -> bool:
    ttl = effect.get(C.EFFECT_TTL)
    return isinstance(ttl, int) and not isinstance(ttl, bool) and (ttl == -1 or 1 <= ttl <= C.EFFECT_MAX_TTL)


def _effect_mechanics_are_useful(effect: dict[str, Any]) -> bool:
    mechanics = effect.get(C.EFFECT_MECHANICS, [])
    if mechanics in (None, []):
        return True
    if not isinstance(mechanics, list):
        return False
    for mechanic in mechanics:
        if not isinstance(mechanic, dict):
            return False
        value = mechanic.get(C.VALUE)
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > C.EFFECT_MECHANIC_MAX_VALUE
        ):
            return False
    return True


def _sanitize_effect_text_fields(
    effect: dict[str, Any],
    *,
    fighter_id: str,
    index: int,
    source: Any,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    sanitized = dict(effect)
    warnings: list[dict[str, Any]] = []
    on_apply = sanitized.get(C.EFFECT_ON_APPLY)
    if on_apply is None and C.EFFECT_ON_APPLY in sanitized:
        return None, [
            _effect_payload_warning(
                fighter_id=fighter_id,
                index=index,
                source=source,
                action="dropped",
                reason="null_on_apply",
                field_suffix=f".{C.EFFECT_ON_APPLY}",
            )
        ]
    if C.EFFECT_ON_TICK in sanitized and sanitized.get(C.EFFECT_ON_TICK) is None:
        sanitized.pop(C.EFFECT_ON_TICK, None)
        warnings.append(
            _effect_payload_warning(
                fighter_id=fighter_id,
                index=index,
                source=source,
                action="repaired",
                reason="null_on_tick_removed",
                field_suffix=f".{C.EFFECT_ON_TICK}",
            )
        )
    return sanitized, warnings


def _canonicalize_effect_target(
    effect: dict[str, Any],
    target_fighter: FighterState,
    *,
    fighter_id: str,
    index: int,
    source: Any,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    metadata = effect.get(C.METADATA)
    if not isinstance(metadata, dict) or C.TARGETED_PART not in metadata:
        return effect, []
    raw_part = metadata.get(C.TARGETED_PART)
    canonical_part = target_fighter.normalize_part_name(cast(str, raw_part))
    if canonical_part is None:
        return None, [
            _effect_payload_warning(
                fighter_id=fighter_id,
                index=index,
                source=source,
                action="dropped",
                reason="unknown_effect_target_part",
                field_suffix=f".{C.METADATA}.{C.TARGETED_PART}",
            )
        ]
    if raw_part == canonical_part:
        return effect, []
    sanitized = dict(effect)
    sanitized[C.METADATA] = {**metadata, C.TARGETED_PART: canonical_part}
    return sanitized, [
        _effect_payload_warning(
            fighter_id=fighter_id,
            index=index,
            source=source,
            action="canonicalized",
            reason="effect_target_alias",
            field_suffix=f".{C.METADATA}.{C.TARGETED_PART}",
            canonical_part=canonical_part,
        )
    ]


def _effect_source_matches_target(
    effect: dict[str, Any],
    *,
    fighter_id: str,
    source: str,
    source_attempt: str,
    opponent_fighter: FighterState,
) -> bool:
    effect_type = effect.get(C.TYPE, C.DEBUFFS)
    if source != fighter_id:
        return True
    if effect_type != C.DEBUFFS:
        return True
    if _attempt_allows_self_wound(source_attempt) or _attempt_self_setup_kind(source_attempt) is not None:
        return True
    return not _attempt_targets_opponent(str(source_attempt or "").lower(), opponent_fighter)


def _authorize_effect_added(
    effect: Any,
    *,
    authorized_sources: set[str],
    target_fighter: FighterState,
    fighter_id: str,
    fighters: dict[str, FighterState],
    index: int,
    attempts: dict[str, str] | None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if not _is_authorized_consequence(effect, authorized_sources, C.EFFECTS_ADDED):
        return None, []
    source = effect.get(C.SOURCE)
    warnings: list[dict[str, Any]] = []
    if not _valid_effect_magnitude(effect):
        return None, [
            _effect_payload_warning(
                fighter_id=fighter_id,
                index=index,
                source=source,
                action="dropped",
                reason="missing_or_invalid_magnitude",
            )
        ]
    if not _valid_effect_ttl(effect):
        return None, [
            _effect_payload_warning(
                fighter_id=fighter_id,
                index=index,
                source=source,
                action="dropped",
                reason="invalid_ttl",
                field_suffix=f".{C.EFFECT_TTL}",
            )
        ]
    if not _effect_mechanics_are_useful(effect):
        return None, [
            _effect_payload_warning(
                fighter_id=fighter_id,
                index=index,
                source=source,
                action="dropped",
                reason="invalid_or_noop_mechanics",
                field_suffix=f".{C.EFFECT_MECHANICS}",
            )
        ]

    sanitized, text_warnings = _sanitize_effect_text_fields(
        effect,
        fighter_id=fighter_id,
        index=index,
        source=source,
    )
    warnings.extend(text_warnings)
    if sanitized is None:
        return None, warnings

    sanitized, target_warnings = _canonicalize_effect_target(
        sanitized,
        target_fighter,
        fighter_id=fighter_id,
        index=index,
        source=source,
    )
    warnings.extend(target_warnings)
    if sanitized is None:
        return None, warnings

    source_attempt = (attempts or {}).get(str(source), "")
    if source in {C.FIGHTER_A, C.FIGHTER_B} and not _effect_source_matches_target(
        sanitized,
        fighter_id=fighter_id,
        source=source,
        source_attempt=source_attempt,
        opponent_fighter=target_fighter if source != fighter_id else fighters[_opponent_id(fighter_id)],
    ):
        warnings.append(
            _phase2_validation_warning(
                code=C.WARNING_CODE_P2_EFFECT_SOURCE_MISMATCH,
                fighter_id=fighter_id,
                field=f"delta.{fighter_id}.{C.EFFECTS_ADDED}[{index}]",
                source=source,
                action="dropped",
                reason="source_attempt_targeted_opponent_not_self",
            )
        )
        return None, warnings

    return _copy_without_source(sanitized), warnings
