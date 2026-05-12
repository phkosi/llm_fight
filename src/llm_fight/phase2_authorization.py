"""Judge Phase 2 delta authorization and target sanitization."""

from __future__ import annotations

from typing import Any, cast

from .engine import constants as C
from .engine.logger import logger
from .state import FighterState


def _attempts_both_invalid_and_failed(p1: dict[str, Any], rolls: dict[str, bool]) -> bool:
    return (
        not rolls.get(C.FIGHTER_A, False)
        and not rolls.get(C.FIGHTER_B, False)
        and not p1.get(f"{C.ATTEMPT}_{C.FIGHTER_A}_valid", False)
        and not p1.get(f"{C.ATTEMPT}_{C.FIGHTER_B}_valid", False)
    )


def _authorized_phase2_sources(p1: dict[str, Any], rolls: dict[str, bool]) -> set[str]:
    return {
        fighter_id
        for fighter_id in (C.FIGHTER_A, C.FIGHTER_B)
        if rolls.get(fighter_id, False) and p1.get(f"{C.ATTEMPT}_{fighter_id}_valid", False)
    }


def _is_authorized_consequence(entry: Any, authorized_sources: set[str], field_name: str) -> bool:
    if not isinstance(entry, dict):
        logger.warning("Dropping Judge Phase 2 %s consequence without source object.", field_name)
        return False
    source = entry.get(C.SOURCE)
    if source not in authorized_sources:
        logger.warning(
            "Dropping Judge Phase 2 %s consequence from unauthorized source %r.",
            field_name,
            source,
        )
        return False
    return True


def _copy_without_source(entry: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(entry)
    sanitized.pop(C.SOURCE, None)
    return sanitized


def _phase2_validation_warning(
    *,
    code: str,
    fighter_id: str,
    field: str,
    source: Any,
    action: str,
    reason: str | None = None,
    canonical_part: str | None = None,
) -> dict[str, Any]:
    warning = {
        "code": code,
        "phase": "judge_phase2",
        "fighter_id": fighter_id,
        "field": field,
        "action": action,
    }
    if source in {C.FIGHTER_A, C.FIGHTER_B}:
        warning[C.SOURCE] = source
    if reason:
        warning["reason"] = reason
    if canonical_part:
        warning["canonical_part"] = canonical_part
    return warning


def _sanitize_phase2_narration(sanitized: dict[str, Any], warnings: list[dict[str, Any]]) -> None:
    invalid_target_warning_codes = {
        C.WARNING_CODE_INVALID_P2_WOUND_TARGET,
        C.WARNING_CODE_INVALID_EFFECT_REMOVAL_TARGET,
    }
    if any(warning.get("code") in invalid_target_warning_codes for warning in warnings):
        sanitized[C.NARRATION] = (
            "The judge referenced an invalid body-part target; only validated consequences are recorded."
        )


def _phase2_known_fields(p2: dict[str, Any]) -> dict[str, Any]:
    sanitized = {
        C.NARRATION: p2.get(C.NARRATION, ""),
        C.DELTA: p2.get(C.DELTA, {}),
        C.FIGHT_END: p2.get(C.FIGHT_END, False),
        C.WINNER: p2.get(C.WINNER),
    }
    metadata = p2.get(C.METADATA)
    if p2.get(C.P2_ENGINE_FALLBACK_MARKER) is True and isinstance(metadata, dict):
        fallback_metadata = {
            key: metadata[key]
            for key in (
                C.P2_FALLBACK_USED,
                C.P2_FALLBACK_REASON,
                C.P2_FALLBACK_POLICY,
                C.P2_LLM_ERROR,
            )
            if key in metadata
        }
        if fallback_metadata.get(C.P2_FALLBACK_USED) is True:
            sanitized[C.METADATA] = fallback_metadata
    return sanitized


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


def _resolve_phase2_effect_removal_target(
    effect_removal: dict[str, Any],
    target_fighter: FighterState,
    fighter_id: str,
    index: int,
) -> tuple[str | None, dict[str, Any] | None]:
    raw_part = effect_removal.get(C.TARGETED_PART)
    if raw_part in (None, ""):
        return None, None
    field = f"delta.{fighter_id}.{C.EFFECTS_REMOVED}[{index}].{C.TARGETED_PART}"
    source = effect_removal.get(C.SOURCE)
    canonical_part = target_fighter.normalize_part_name(cast(str, raw_part))
    if canonical_part is None:
        logger.warning(
            "Dropping Judge Phase 2 effect removal with invalid target for fighter %s.",
            fighter_id,
        )
        return None, _phase2_validation_warning(
            code=C.WARNING_CODE_INVALID_EFFECT_REMOVAL_TARGET,
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


def _invalid_phase2_effect_removal_target_warnings(
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
        for index, effect_removal in enumerate(delta.get(C.EFFECTS_REMOVED, [])):
            if not isinstance(effect_removal, dict):
                continue
            _, warning = _resolve_phase2_effect_removal_target(
                effect_removal,
                fighters[fighter_id],
                fighter_id,
                index,
            )
            if warning is not None:
                warnings.append(warning)
    return warnings


def _warning_key(warning: dict[str, Any]) -> tuple[Any, Any]:
    return warning.get("code"), warning.get("field")


def _merge_phase2_warnings(*warning_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen = set()
    for warnings in warning_groups:
        for warning in warnings:
            key = _warning_key(warning)
            if key in seen:
                continue
            seen.add(key)
            merged.append(warning)
    return merged


def _authorized_scalar_value(entry: Any, authorized_sources: set[str], field_name: str) -> Any:
    if not _is_authorized_consequence(entry, authorized_sources, field_name):
        return None
    return entry.get(C.VALUE)


def _authorize_fighter_delta(
    delta: Any,
    authorized_sources: set[str],
    target_fighter: FighterState,
    fighter_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(delta, dict):
        return {}, []

    authorized_delta: dict[str, Any] = {}
    warnings: list[dict[str, Any]] = []
    for field_name in (C.PAIN_INCREASE, C.EXHAUSTION_INCREASE, C.HEAT_INCREASE, C.STATUS_CHANGE):
        if field_name not in delta:
            continue
        value = _authorized_scalar_value(delta[field_name], authorized_sources, field_name)
        if value is not None:
            authorized_delta[field_name] = value

    wounds = []
    for index, wound in enumerate(delta.get(C.WOUNDS, [])):
        if _is_authorized_consequence(wound, authorized_sources, C.WOUNDS):
            source = wound.get(C.SOURCE)
            canonical_part, warning = _resolve_phase2_wound_target(wound, target_fighter, fighter_id, index)
            if warning is not None:
                warnings.append(warning)
                continue

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
            wounds.append(sanitized_wound)
    if wounds:
        authorized_delta[C.WOUNDS] = wounds

    effects_added = []
    for effect in delta.get(C.EFFECTS_ADDED, []):
        if _is_authorized_consequence(effect, authorized_sources, C.EFFECTS_ADDED):
            effects_added.append(_copy_without_source(effect))
    if effects_added:
        authorized_delta[C.EFFECTS_ADDED] = effects_added

    effects_removed = []
    for index, effect_removal in enumerate(delta.get(C.EFFECTS_REMOVED, [])):
        if _is_authorized_consequence(effect_removal, authorized_sources, C.EFFECTS_REMOVED):
            sanitized_removal = _copy_without_source(effect_removal)
            canonical_part, warning = _resolve_phase2_effect_removal_target(
                effect_removal,
                target_fighter,
                fighter_id,
                index,
            )
            if warning is not None:
                warnings.append(warning)
                continue
            if canonical_part is not None:
                if sanitized_removal.get(C.TARGETED_PART) != canonical_part:
                    warnings.append(
                        _phase2_validation_warning(
                            code=C.WARNING_CODE_CANONICALIZED_EFFECT_REMOVAL_TARGET,
                            fighter_id=fighter_id,
                            field=f"delta.{fighter_id}.{C.EFFECTS_REMOVED}[{index}].{C.TARGETED_PART}",
                            source=effect_removal.get(C.SOURCE),
                            action="canonicalized",
                            canonical_part=canonical_part,
                        )
                    )
                sanitized_removal[C.TARGETED_PART] = canonical_part
            effects_removed.append(sanitized_removal)
    if effects_removed:
        authorized_delta[C.EFFECTS_REMOVED] = effects_removed

    return authorized_delta, warnings


def authorize_phase2_result(
    p2: dict[str, Any],
    p1: dict[str, Any],
    rolls: dict[str, bool],
    fighters: dict[str, FighterState],
) -> dict[str, Any]:
    """Return a source-authorized and target-sanitized Judge Phase 2 result."""
    authorized_sources = _authorized_phase2_sources(p1, rolls)
    sanitized = _phase2_known_fields(p2)
    raw_delta = p2.get(C.DELTA, {})
    invalid_target_warnings = _merge_phase2_warnings(
        _invalid_phase2_wound_target_warnings(raw_delta, fighters),
        _invalid_phase2_effect_removal_target_warnings(raw_delta, fighters),
    )

    if not authorized_sources:
        if p2.get(C.DELTA) or p2.get(C.FIGHT_END) or p2.get(C.WINNER) is not None:
            logger.warning("Ignoring Judge Phase 2 damage/end result because no valid attempt succeeded.")
            if _attempts_both_invalid_and_failed(p1, rolls):
                logger.warning("both attempts were invalid and failed.")
        if invalid_target_warnings:
            sanitized[C.VALIDATION_WARNINGS] = invalid_target_warnings
            _sanitize_phase2_narration(sanitized, invalid_target_warnings)
        sanitized[C.DELTA] = {}
        sanitized[C.FIGHT_END] = False
        sanitized[C.WINNER] = None
        return sanitized

    if not isinstance(raw_delta, dict):
        sanitized[C.DELTA] = {}
        return sanitized

    sanitized_delta: dict[str, Any] = {}
    warnings: list[dict[str, Any]] = []
    for fighter_id in (C.FIGHTER_A, C.FIGHTER_B):
        authorized_delta, delta_warnings = _authorize_fighter_delta(
            raw_delta.get(fighter_id, {}),
            authorized_sources,
            fighters[fighter_id],
            fighter_id,
        )
        warnings.extend(delta_warnings)
        if authorized_delta:
            sanitized_delta[fighter_id] = authorized_delta

    sanitized[C.DELTA] = sanitized_delta
    warnings = _merge_phase2_warnings(warnings, invalid_target_warnings)
    if warnings:
        sanitized[C.VALIDATION_WARNINGS] = warnings
        _sanitize_phase2_narration(sanitized, warnings)
    terminal_suppression_warning_codes = {
        C.WARNING_CODE_INVALID_P2_WOUND_TARGET,
        C.WARNING_CODE_INVALID_EFFECT_REMOVAL_TARGET,
    }
    if not sanitized_delta and any(warning.get("code") in terminal_suppression_warning_codes for warning in warnings):
        sanitized[C.FIGHT_END] = False
        sanitized[C.WINNER] = None
    return sanitized
