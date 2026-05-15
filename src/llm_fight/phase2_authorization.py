"""Judge Phase 2 delta authorization and target sanitization."""

from __future__ import annotations

import re
from typing import Any, cast

from .engine import constants as C
from .engine.logger import logger
from .phase2_common import (
    _attempts_both_invalid_and_failed,
    _authorized_phase2_sources,
    _copy_without_source,
    _is_authorized_consequence,
    _merge_phase2_warnings,
    _phase2_validation_warning,
)
from .phase2_effects import _authorize_effect_added
from .phase2_repairs import (
    _no_effect_warnings_for_unresolved_damage,
    _repair_missing_successful_damage,
    _repair_missing_successful_setup,
    _successful_damage_sources,
    _successful_unresolved_damage_sources,
)
from .phase2_text import (
    _attempt_allows_self_wound,
    _attempt_has_damage_intent,
    _attempt_mentions_body_part,
    _display_name,
    _readable_part,
)
from .phase2_wounds import _authorize_wounds, _invalid_phase2_wound_target_warnings
from .state import FighterState


def _sanitize_phase2_narration(sanitized: dict[str, Any], warnings: list[dict[str, Any]]) -> None:
    if any(warning.get("code") == C.WARNING_CODE_P2_NO_EFFECT for warning in warnings):
        sanitized[C.NARRATION] = (
            "A successful damage attempt had no resolvable target, so no mechanical effect was applied."
        )
        return
    invalid_target_warning_codes = {
        C.WARNING_CODE_INVALID_P2_WOUND_TARGET,
        C.WARNING_CODE_INVALID_EFFECT_REMOVAL_TARGET,
        C.WARNING_CODE_P2_WOUND_SOURCE_MISMATCH,
        C.WARNING_CODE_P2_WOUND_TARGET_MISMATCH,
        C.WARNING_CODE_P2_WOUND_WITHOUT_DAMAGE_INTENT,
        C.WARNING_CODE_P2_WOUND_TYPE_MISMATCH,
        C.WARNING_CODE_P2_SCALAR_SOURCE_MISMATCH,
        C.WARNING_CODE_INVALID_EFFECT_PAYLOAD,
        C.WARNING_CODE_P2_EFFECT_SOURCE_MISMATCH,
    }
    if any(warning.get("code") in invalid_target_warning_codes for warning in warnings):
        sanitized[C.NARRATION] = (
            "The judge's mechanical target conflicted with the current actions; "
            "only validated consequences are recorded."
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


def _authorized_scalar_value(
    entry: Any,
    authorized_sources: set[str],
    field_name: str,
    fighter_id: str,
    attempts: dict[str, str] | None,
) -> tuple[Any, dict[str, Any] | None]:
    if not _is_authorized_consequence(entry, authorized_sources, field_name):
        return None, None
    source = entry.get(C.SOURCE)
    source_attempt = (attempts or {}).get(str(source), "")
    if (
        source_attempt
        and source == fighter_id
        and field_name in {C.PAIN_INCREASE, C.HEAT_INCREASE, C.STATUS_CHANGE}
        and _attempt_mentions_body_part(source_attempt)
        and not _attempt_allows_self_wound(source_attempt)
    ):
        return None, _phase2_validation_warning(
            code=C.WARNING_CODE_P2_SCALAR_SOURCE_MISMATCH,
            fighter_id=fighter_id,
            field=f"delta.{fighter_id}.{field_name}",
            source=source,
            action="dropped",
            reason="source_attempt_did_not_describe_self_consequence",
        )
    if (
        source_attempt
        and source != fighter_id
        and field_name in {C.PAIN_INCREASE, C.HEAT_INCREASE, C.STATUS_CHANGE}
        and ("smoke bomb" in source_attempt.lower() or _attempt_mentions_body_part(source_attempt))
        and not _attempt_has_damage_intent(source_attempt)
    ):
        return None, _phase2_validation_warning(
            code=C.WARNING_CODE_P2_WOUND_WITHOUT_DAMAGE_INTENT,
            fighter_id=fighter_id,
            field=f"delta.{fighter_id}.{field_name}",
            source=source,
            action="dropped",
            reason="source_attempt_did_not_describe_damage",
        )
    return entry.get(C.VALUE), None


def _authorize_scalar_fields(
    delta: Any,
    authorized_sources: set[str],
    fighter_id: str,
    attempts: dict[str, str] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    authorized_delta: dict[str, Any] = {}
    warnings: list[dict[str, Any]] = []
    for field_name in (C.PAIN_INCREASE, C.EXHAUSTION_INCREASE, C.HEAT_INCREASE, C.STATUS_CHANGE):
        if field_name not in delta:
            continue
        value, warning = _authorized_scalar_value(
            delta[field_name], authorized_sources, field_name, fighter_id, attempts
        )
        if warning is not None:
            warnings.append(warning)
        if value is not None:
            authorized_delta[field_name] = value
    return authorized_delta, warnings


def _authorize_effects_added(
    delta: dict[str, Any],
    authorized_sources: set[str],
    target_fighter: FighterState,
    fighter_id: str,
    fighters: dict[str, FighterState],
    attempts: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    effects_added: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for index, effect in enumerate(delta.get(C.EFFECTS_ADDED, [])):
        sanitized_effect, effect_warnings = _authorize_effect_added(
            effect,
            authorized_sources=authorized_sources,
            target_fighter=target_fighter,
            fighter_id=fighter_id,
            fighters=fighters,
            index=index,
            attempts=attempts,
        )
        warnings.extend(effect_warnings)
        if sanitized_effect is not None:
            effects_added.append(sanitized_effect)
    return effects_added, warnings


def _authorize_effects_removed(
    delta: dict[str, Any],
    authorized_sources: set[str],
    target_fighter: FighterState,
    fighter_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    effects_removed: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for index, effect_removal in enumerate(delta.get(C.EFFECTS_REMOVED, [])):
        if not _is_authorized_consequence(effect_removal, authorized_sources, C.EFFECTS_REMOVED):
            continue
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
    return effects_removed, warnings


def _authorize_fighter_delta(
    delta: Any,
    authorized_sources: set[str],
    target_fighter: FighterState,
    fighter_id: str,
    fighters: dict[str, FighterState],
    narration: str,
    attempts: dict[str, str] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], set[str]]:
    if not isinstance(delta, dict):
        return {}, [], set()

    authorized_delta, warnings = _authorize_scalar_fields(delta, authorized_sources, fighter_id, attempts)
    wounds, wound_warnings, wound_sources = _authorize_wounds(
        delta,
        authorized_sources,
        target_fighter,
        fighter_id,
        fighters,
        narration,
        attempts,
    )
    warnings.extend(wound_warnings)
    if wounds:
        authorized_delta[C.WOUNDS] = wounds

    effects_added, effect_warnings = _authorize_effects_added(
        delta,
        authorized_sources,
        target_fighter,
        fighter_id,
        fighters,
        attempts,
    )
    warnings.extend(effect_warnings)
    if effects_added:
        authorized_delta[C.EFFECTS_ADDED] = effects_added

    effects_removed, removal_warnings = _authorize_effects_removed(
        delta,
        authorized_sources,
        target_fighter,
        fighter_id,
    )
    warnings.extend(removal_warnings)
    if effects_removed:
        authorized_delta[C.EFFECTS_REMOVED] = effects_removed

    return authorized_delta, warnings, wound_sources


def _narration_has_failure_for_source(narration: str, source_id: str, source_fighter: FighterState) -> bool:
    text = str(narration or "").lower()
    names = {
        source_id.lower(),
        f"fighter {source_id.lower()}",
        _display_name(source_fighter).lower(),
    }
    failure_terms = r"\b(fail|fails|failed|miss|misses|missed|invalid)\b"
    return any(re.search(rf"{re.escape(name)}.{{0,180}}{failure_terms}", text) for name in names)


def _mechanical_resolution_narration(
    damage_sources: list[tuple[str, str, str]],
    setup_sources: list[tuple[str, str, str]],
    fighters: dict[str, FighterState],
) -> str:
    clauses = [
        (
            f"{_display_name(fighters[source_id])}'s successful attack lands on "
            f"{_display_name(fighters[target_id])}'s {_readable_part(target_part)}"
        )
        for source_id, target_id, target_part in damage_sources
    ]
    clauses.extend(
        (
            f"{_display_name(fighters[source_id])}'s successful setup leaves "
            f"{_display_name(fighters[target_id])} {effect_name}"
        )
        for source_id, target_id, effect_name in setup_sources
    )
    if not clauses:
        return "The validated exchange resolves from the successful rolls."
    return "Validated mechanics resolve the exchange: " + "; ".join(clauses) + "."


def _reject_phase2_without_sources(
    sanitized: dict[str, Any],
    p2: dict[str, Any],
    p1: dict[str, Any],
    rolls: dict[str, bool],
    invalid_target_warnings: list[dict[str, Any]],
) -> dict[str, Any]:
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


def _authorize_phase2_deltas(
    raw_delta: dict[str, Any],
    authorized_sources: set[str],
    fighters: dict[str, FighterState],
    narration: str,
    attempts: dict[str, str] | None,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, set[str]]]:
    sanitized_delta: dict[str, Any] = {}
    warnings: list[dict[str, Any]] = []
    wound_sources_by_target: dict[str, set[str]] = {}
    for fighter_id in (C.FIGHTER_A, C.FIGHTER_B):
        authorized_delta, delta_warnings, wound_sources = _authorize_fighter_delta(
            raw_delta.get(fighter_id, {}),
            authorized_sources,
            fighters[fighter_id],
            fighter_id,
            fighters,
            narration,
            attempts=attempts,
        )
        warnings.extend(delta_warnings)
        wound_sources_by_target[fighter_id] = wound_sources
        if authorized_delta:
            sanitized_delta[fighter_id] = authorized_delta
    return sanitized_delta, warnings, wound_sources_by_target


def _repair_phase2_deltas(
    sanitized_delta: dict[str, Any],
    wound_sources_by_target: dict[str, set[str]],
    authorized_sources: set[str],
    attempts: dict[str, str] | None,
    fighters: dict[str, FighterState],
) -> tuple[list[dict[str, Any]], list[tuple[str, str, str]], list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    damage_sources = _successful_damage_sources(authorized_sources, attempts, fighters)
    unresolved_damage_sources = _successful_unresolved_damage_sources(authorized_sources, attempts, fighters)
    repair_warnings, repaired_sources = _repair_missing_successful_damage(
        sanitized_delta=sanitized_delta,
        wound_sources_by_target=wound_sources_by_target,
        damage_sources=damage_sources,
        attempts=attempts,
    )
    no_effect_warnings = _no_effect_warnings_for_unresolved_damage(unresolved_damage_sources, wound_sources_by_target)
    setup_repair_warnings, repaired_setups = _repair_missing_successful_setup(
        sanitized_delta=sanitized_delta,
        authorized_sources=authorized_sources,
        attempts=attempts,
        fighters=fighters,
    )
    return (
        _merge_phase2_warnings(repair_warnings, setup_repair_warnings, no_effect_warnings),
        damage_sources,
        repaired_sources,
        repaired_setups,
    )


def _mark_engine_repairs(
    sanitized: dict[str, Any],
    repaired_sources: list[tuple[str, str, str]],
    repaired_setups: list[tuple[str, str, str]],
) -> None:
    if not repaired_sources and not repaired_setups:
        return
    metadata = sanitized.setdefault(C.METADATA, {})
    if isinstance(metadata, dict):
        metadata[C.P2_ENGINE_REPAIR_USED] = True
    sanitized[C.FIGHT_END] = False
    sanitized[C.WINNER] = None


def _apply_phase2_narration_repairs(
    sanitized: dict[str, Any],
    warnings: list[dict[str, Any]],
    damage_sources: list[tuple[str, str, str]],
    repaired_sources: list[tuple[str, str, str]],
    repaired_setups: list[tuple[str, str, str]],
    fighters: dict[str, FighterState],
    attempts: dict[str, str] | None,
) -> list[dict[str, Any]]:
    if repaired_sources or repaired_setups:
        sanitized[C.NARRATION] = _mechanical_resolution_narration(damage_sources, repaired_setups, fighters)
        return warnings
    if attempts is None:
        return warnings

    mismatched_sources = [
        source_id
        for source_id, _, _ in damage_sources
        if _narration_has_failure_for_source(str(sanitized.get(C.NARRATION, "")), source_id, fighters[source_id])
    ]
    if not mismatched_sources:
        return warnings
    mismatch_warnings = [
        _phase2_validation_warning(
            code=C.WARNING_CODE_P2_NARRATION_ROLL_MISMATCH,
            fighter_id=source_id,
            field=C.NARRATION,
            source=source_id,
            action="replaced",
            reason="narration_contradicted_successful_roll",
        )
        for source_id in mismatched_sources
    ]
    warnings = _merge_phase2_warnings(warnings, mismatch_warnings)
    sanitized[C.VALIDATION_WARNINGS] = warnings
    sanitized[C.NARRATION] = _mechanical_resolution_narration(damage_sources, [], fighters)
    return warnings


def _suppress_terminal_for_invalid_empty_delta(
    sanitized: dict[str, Any],
    sanitized_delta: dict[str, Any],
    warnings: list[dict[str, Any]],
) -> None:
    terminal_suppression_warning_codes = {
        C.WARNING_CODE_INVALID_P2_WOUND_TARGET,
        C.WARNING_CODE_INVALID_EFFECT_REMOVAL_TARGET,
        C.WARNING_CODE_P2_WOUND_SOURCE_MISMATCH,
        C.WARNING_CODE_P2_WOUND_TARGET_MISMATCH,
        C.WARNING_CODE_P2_WOUND_WITHOUT_DAMAGE_INTENT,
        C.WARNING_CODE_P2_WOUND_TYPE_MISMATCH,
        C.WARNING_CODE_INVALID_EFFECT_PAYLOAD,
        C.WARNING_CODE_P2_EFFECT_SOURCE_MISMATCH,
        C.WARNING_CODE_P2_NO_EFFECT,
    }
    if not sanitized_delta and any(warning.get("code") in terminal_suppression_warning_codes for warning in warnings):
        sanitized[C.FIGHT_END] = False
        sanitized[C.WINNER] = None


def authorize_phase2_result(
    p2: dict[str, Any],
    p1: dict[str, Any],
    rolls: dict[str, bool],
    fighters: dict[str, FighterState],
    *,
    attempts: dict[str, str] | None = None,
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
        return _reject_phase2_without_sources(sanitized, p2, p1, rolls, invalid_target_warnings)

    if not isinstance(raw_delta, dict):
        sanitized[C.DELTA] = {}
        return sanitized

    narration = str(sanitized.get(C.NARRATION, ""))
    sanitized_delta, warnings, wound_sources_by_target = _authorize_phase2_deltas(
        raw_delta, authorized_sources, fighters, narration, attempts
    )
    repair_warnings, damage_sources, repaired_sources, repaired_setups = _repair_phase2_deltas(
        sanitized_delta, wound_sources_by_target, authorized_sources, attempts, fighters
    )
    _mark_engine_repairs(sanitized, repaired_sources, repaired_setups)

    sanitized[C.DELTA] = sanitized_delta
    warnings = _merge_phase2_warnings(warnings, invalid_target_warnings, repair_warnings)
    if warnings:
        sanitized[C.VALIDATION_WARNINGS] = warnings
        _sanitize_phase2_narration(sanitized, warnings)
    warnings = _apply_phase2_narration_repairs(
        sanitized, warnings, damage_sources, repaired_sources, repaired_setups, fighters, attempts
    )
    _suppress_terminal_for_invalid_empty_delta(sanitized, sanitized_delta, warnings)
    return sanitized
