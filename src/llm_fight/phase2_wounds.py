"""Wound authorization helpers for Judge Phase 2."""

from __future__ import annotations

from typing import Any, cast

from .engine import constants as C
from .engine.logger import logger
from .phase2_common import _copy_without_source, _is_authorized_consequence, _phase2_validation_warning
from .phase2_text import (
    _attempt_allows_self_wound,
    _attempt_has_damage_intent,
    _mentioned_opponent_parts,
    _mentioned_owned_parts,
    _mentioned_target_parts,
    _wound_type_supported_by_attempt,
)
from .state import FighterState


def _resolve_phase2_wound_target(
    wound: dict[str, Any],
    target_fighter: FighterState,
    fighter_id: str,
    index: int,
) -> tuple[str | None, dict[str, Any] | None]:
    field = f"delta.{fighter_id}.{C.WOUNDS}[{index}].{C.TARGETED_PART}"
    source = wound.get(C.SOURCE)
    canonical_part = target_fighter.normalize_part_name(cast(str, wound.get(C.TARGETED_PART)))
    if canonical_part is None:
        logger.warning(
            "Dropping Judge Phase 2 wound with invalid target for fighter %s.",
            fighter_id,
        )
        return None, _phase2_validation_warning(
            code=C.WARNING_CODE_INVALID_P2_WOUND_TARGET,
            fighter_id=fighter_id,
            field=field,
            source=source,
            action="dropped",
            reason="unknown_target_part",
        )
    return canonical_part, None


def _invalid_phase2_wound_target_warnings(
    raw_delta: Any,
    fighters: dict[str, FighterState],
) -> list[dict[str, Any]]:
    if not isinstance(raw_delta, dict):
        return []

    warnings: list[dict[str, Any]] = []
    for fighter_id in (C.FIGHTER_A, C.FIGHTER_B):
        delta = raw_delta.get(fighter_id, {})
        if not isinstance(delta, dict):
            continue
        for index, wound in enumerate(delta.get(C.WOUNDS, [])):
            if not isinstance(wound, dict):
                continue
            _, warning = _resolve_phase2_wound_target(wound, fighters[fighter_id], fighter_id, index)
            if warning is not None:
                warnings.append(warning)
    return warnings


def _canonicalize_wound_part_from_text(
    *,
    canonical_part: str,
    field: str,
    source: Any,
    source_attempt: str,
    source_fighter: FighterState | None,
    target_fighter: FighterState,
    fighter_id: str,
    narration: str,
) -> tuple[str | None, list[dict[str, Any]]]:
    warnings: list[dict[str, Any]] = []
    if source_attempt and source_fighter is not None:
        mentioned_parts = _mentioned_opponent_parts(source_attempt, source_fighter, target_fighter)
    else:
        mentioned_parts = _mentioned_target_parts(source_attempt, target_fighter) if source_attempt else set()

    if mentioned_parts and canonical_part not in mentioned_parts:
        if len(mentioned_parts) != 1:
            return None, [
                _phase2_validation_warning(
                    code=C.WARNING_CODE_P2_WOUND_TARGET_MISMATCH,
                    fighter_id=fighter_id,
                    field=f"{field}.{C.TARGETED_PART}",
                    source=source,
                    action="dropped",
                    reason="source_attempt_named_different_targets",
                )
            ]
        canonical_part = next(iter(mentioned_parts))
        warnings.append(
            _phase2_validation_warning(
                code=C.WARNING_CODE_CANONICALIZED_P2_WOUND_TARGET,
                fighter_id=fighter_id,
                field=f"{field}.{C.TARGETED_PART}",
                source=source,
                action="canonicalized",
                reason="source_attempt_named_different_target",
                canonical_part=canonical_part,
            )
        )

    narration_parts = _mentioned_owned_parts(narration, target_fighter) if not mentioned_parts else set()
    if len(narration_parts) == 1 and canonical_part not in narration_parts:
        canonical_part = next(iter(narration_parts))
        warnings.append(
            _phase2_validation_warning(
                code=C.WARNING_CODE_CANONICALIZED_P2_WOUND_TARGET,
                fighter_id=fighter_id,
                field=f"{field}.{C.TARGETED_PART}",
                source=source,
                action="canonicalized",
                reason="narration_named_different_target",
                canonical_part=canonical_part,
            )
        )
    return canonical_part, warnings


def _authorize_wound(
    wound: Any,
    *,
    index: int,
    authorized_sources: set[str],
    target_fighter: FighterState,
    fighter_id: str,
    fighters: dict[str, FighterState],
    narration: str,
    attempts: dict[str, str] | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str | None]:
    if not _is_authorized_consequence(wound, authorized_sources, C.WOUNDS):
        return None, [], None

    source = wound.get(C.SOURCE)
    field = f"delta.{fighter_id}.{C.WOUNDS}[{index}]"
    source_attempt = (attempts or {}).get(str(source), "")
    source_fighter = fighters.get(str(source))
    warnings: list[dict[str, Any]] = []
    if source_attempt and source == fighter_id and not _attempt_allows_self_wound(source_attempt):
        return (
            None,
            [
                _phase2_validation_warning(
                    code=C.WARNING_CODE_P2_WOUND_SOURCE_MISMATCH,
                    fighter_id=fighter_id,
                    field=field,
                    source=source,
                    action="dropped",
                    reason="source_attempt_did_not_describe_self_wound",
                )
            ],
            None,
        )
    if source_attempt and not _attempt_has_damage_intent(source_attempt):
        return (
            None,
            [
                _phase2_validation_warning(
                    code=C.WARNING_CODE_P2_WOUND_WITHOUT_DAMAGE_INTENT,
                    fighter_id=fighter_id,
                    field=field,
                    source=source,
                    action="dropped",
                    reason="source_attempt_did_not_describe_damage",
                )
            ],
            None,
        )

    canonical_part, warning = _resolve_phase2_wound_target(wound, target_fighter, fighter_id, index)
    if warning is not None:
        return None, [warning], None
    canonical_part = cast(str, canonical_part)
    if source_attempt and not _wound_type_supported_by_attempt(wound, source_attempt):
        return (
            None,
            [
                _phase2_validation_warning(
                    code=C.WARNING_CODE_P2_WOUND_TYPE_MISMATCH,
                    fighter_id=fighter_id,
                    field=f"{field}.{C.TYPE}",
                    source=source,
                    action="dropped",
                    reason="source_attempt_did_not_support_damage_type",
                )
            ],
            None,
        )

    canonical_part, part_warnings = _canonicalize_wound_part_from_text(
        canonical_part=canonical_part,
        field=field,
        source=source,
        source_attempt=source_attempt,
        source_fighter=source_fighter,
        target_fighter=target_fighter,
        fighter_id=fighter_id,
        narration=narration,
    )
    warnings.extend(part_warnings)
    if canonical_part is None:
        return None, warnings, None

    sanitized_wound = _copy_without_source(wound)
    if sanitized_wound.get(C.TARGETED_PART) != canonical_part:
        warnings.append(
            _phase2_validation_warning(
                code=C.WARNING_CODE_CANONICALIZED_P2_WOUND_TARGET,
                fighter_id=fighter_id,
                field=f"delta.{fighter_id}.{C.WOUNDS}[{index}].{C.TARGETED_PART}",
                source=source,
                action="canonicalized",
                canonical_part=canonical_part,
            )
        )
    sanitized_wound[C.TARGETED_PART] = canonical_part
    wound_source = source if source in {C.FIGHTER_A, C.FIGHTER_B} else None
    return sanitized_wound, warnings, wound_source


def _authorize_wounds(
    delta: dict[str, Any],
    authorized_sources: set[str],
    target_fighter: FighterState,
    fighter_id: str,
    fighters: dict[str, FighterState],
    narration: str,
    attempts: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[str]]:
    wounds: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    wound_sources: set[str] = set()
    for index, wound in enumerate(delta.get(C.WOUNDS, [])):
        sanitized_wound, wound_warnings, wound_source = _authorize_wound(
            wound,
            index=index,
            authorized_sources=authorized_sources,
            target_fighter=target_fighter,
            fighter_id=fighter_id,
            fighters=fighters,
            narration=narration,
            attempts=attempts,
        )
        warnings.extend(wound_warnings)
        if sanitized_wound is not None:
            wounds.append(sanitized_wound)
        if wound_source is not None:
            wound_sources.add(wound_source)
    return wounds, warnings, wound_sources
