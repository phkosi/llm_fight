"""Deterministic repair helpers for Judge Phase 2 authorization."""

from __future__ import annotations

from typing import Any

from .engine import constants as C
from .phase2_common import _phase2_validation_warning
from .phase2_text import (
    _attempt_has_damage_intent,
    _attempt_self_setup_kind,
    _attempt_setup_kind,
    _damage_type_from_attempt,
    _display_name,
    _opponent_id,
    _repair_target_part,
    _setup_target_part,
)
from .state import FighterState


def _successful_damage_sources(
    authorized_sources: set[str],
    attempts: dict[str, str] | None,
    fighters: dict[str, FighterState],
) -> list[tuple[str, str, str]]:
    if attempts is None:
        return []

    damage_sources: list[tuple[str, str, str]] = []
    for source_id in (C.FIGHTER_A, C.FIGHTER_B):
        if source_id not in authorized_sources:
            continue
        source_attempt = attempts.get(source_id, "")
        if not _attempt_has_damage_intent(source_attempt):
            continue
        target_id = _opponent_id(source_id)
        target_part = _repair_target_part(source_attempt, fighters[source_id], fighters[target_id])
        if target_part is None:
            continue
        damage_sources.append((source_id, target_id, target_part))
    return damage_sources


def _successful_unresolved_damage_sources(
    authorized_sources: set[str],
    attempts: dict[str, str] | None,
    fighters: dict[str, FighterState],
) -> list[tuple[str, str]]:
    if attempts is None:
        return []

    unresolved: list[tuple[str, str]] = []
    for source_id in (C.FIGHTER_A, C.FIGHTER_B):
        if source_id not in authorized_sources:
            continue
        source_attempt = attempts.get(source_id, "")
        if not _attempt_has_damage_intent(source_attempt):
            continue
        target_id = _opponent_id(source_id)
        if _repair_target_part(source_attempt, fighters[source_id], fighters[target_id]) is None:
            unresolved.append((source_id, target_id))
    return unresolved


def _no_effect_warnings_for_unresolved_damage(
    unresolved_sources: list[tuple[str, str]],
    wound_sources_by_target: dict[str, set[str]],
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for source_id, target_id in unresolved_sources:
        if source_id in wound_sources_by_target.get(target_id, set()):
            continue
        warnings.append(
            _phase2_validation_warning(
                code=C.WARNING_CODE_P2_NO_EFFECT,
                fighter_id=target_id,
                field=f"delta.{target_id}.{C.WOUNDS}",
                source=source_id,
                action="none",
                reason="successful_damage_attempt_without_resolvable_target",
            )
        )
    return warnings


def _repair_missing_successful_damage(
    *,
    sanitized_delta: dict[str, Any],
    wound_sources_by_target: dict[str, set[str]],
    damage_sources: list[tuple[str, str, str]],
    attempts: dict[str, str] | None,
) -> tuple[list[dict[str, Any]], list[tuple[str, str, str]]]:
    if attempts is None:
        return [], []

    warnings: list[dict[str, Any]] = []
    repaired_sources: list[tuple[str, str, str]] = []
    for source_id, target_id, target_part in damage_sources:
        if source_id in wound_sources_by_target.get(target_id, set()):
            continue
        target_delta = sanitized_delta.setdefault(target_id, {})
        wounds = target_delta.setdefault(C.WOUNDS, [])
        source_attempt = attempts.get(source_id, "")
        wounds.append(
            {
                C.TARGETED_PART: target_part,
                C.VALUE: 10,
                C.TYPE: _damage_type_from_attempt(source_attempt),
            }
        )
        wound_sources_by_target.setdefault(target_id, set()).add(source_id)
        warnings.append(
            _phase2_validation_warning(
                code=C.WARNING_CODE_P2_MECHANICAL_REPAIR,
                fighter_id=target_id,
                field=f"delta.{target_id}.{C.WOUNDS}",
                source=source_id,
                action="added",
                reason="successful_damage_attempt_missing_authorized_wound",
                canonical_part=target_part,
            )
        )
        repaired_sources.append((source_id, target_id, target_part))
    return warnings, repaired_sources


def _fighter_has_effect(fighter: FighterState, effect_name: str) -> bool:
    return any(effect.name == effect_name for effect in [*fighter.buffs, *fighter.debuffs])


def _delta_has_effect(sanitized_delta: dict[str, Any], fighter_id: str, effect_name: str) -> bool:
    delta = sanitized_delta.get(fighter_id, {})
    if not isinstance(delta, dict):
        return False
    return any(
        effect.get(C.NAME) == effect_name for effect in delta.get(C.EFFECTS_ADDED, []) if isinstance(effect, dict)
    )


def _setup_effect_payload(
    *,
    effect_name: str,
    target_id: str,
    target_part: str | None,
    fighters: dict[str, FighterState],
) -> dict[str, Any]:
    target_name = _display_name(fighters[target_id])
    if effect_name == "obscured":
        payload = {
            C.NAME: "obscured",
            C.VALUE: 1,
            C.EFFECT_TTL: 2,
            C.TYPE: C.DEBUFFS,
            C.EFFECT_ON_APPLY: f"{target_name} is obscured by smoke.",
            C.EFFECT_ON_TICK: "The smoke lingers.",
            C.EFFECT_MECHANICS: [
                {
                    C.EFFECT_MECHANIC_KIND: C.EFFECT_MECHANIC_TARGETING_MODIFIER,
                    C.EFFECT_MECHANIC_MODIFIER: C.EFFECT_MECHANIC_OUTGOING_ACCURACY_PENALTY,
                    C.VALUE: 20,
                }
            ],
            C.EFFECT_TAGS: ["smoke", "obscurity"],
        }
    else:
        payload = {
            C.NAME: "flanked",
            C.VALUE: 1,
            C.EFFECT_TTL: 2,
            C.TYPE: C.DEBUFFS,
            C.EFFECT_ON_APPLY: f"{target_name} is pressured from a bad angle.",
            C.EFFECT_ON_TICK: "The bad angle remains dangerous.",
            C.EFFECT_MECHANICS: [
                {
                    C.EFFECT_MECHANIC_KIND: C.EFFECT_MECHANIC_TARGETING_MODIFIER,
                    C.EFFECT_MECHANIC_MODIFIER: C.EFFECT_MECHANIC_OUTGOING_ACCURACY_PENALTY,
                    C.VALUE: 10,
                }
            ],
            C.EFFECT_TAGS: ["positioning"],
        }
    if effect_name == "guarded":
        payload = {
            C.NAME: "guarded",
            C.VALUE: 1,
            C.EFFECT_TTL: 2,
            C.TYPE: C.BUFFS,
            C.EFFECT_ON_APPLY: f"{target_name} settles into a guarded stance.",
            C.EFFECT_ON_TICK: "The guarded stance holds.",
            C.EFFECT_TAGS: ["guard"],
        }
    if target_part is not None:
        payload[C.METADATA] = {C.TARGETED_PART: target_part}
    return payload


def _repair_missing_successful_setup(
    *,
    sanitized_delta: dict[str, Any],
    authorized_sources: set[str],
    attempts: dict[str, str] | None,
    fighters: dict[str, FighterState],
) -> tuple[list[dict[str, Any]], list[tuple[str, str, str]]]:
    if attempts is None:
        return [], []

    warnings: list[dict[str, Any]] = []
    repaired_sources: list[tuple[str, str, str]] = []
    for source_id in (C.FIGHTER_A, C.FIGHTER_B):
        if source_id not in authorized_sources:
            continue
        source_attempt = attempts.get(source_id, "")
        target_id = _opponent_id(source_id)
        setup_kind = _attempt_setup_kind(source_attempt, fighters[target_id])
        if setup_kind is not None and not (
            _fighter_has_effect(fighters[target_id], setup_kind)
            or _delta_has_effect(
                sanitized_delta,
                target_id,
                setup_kind,
            )
        ):
            target_part = _setup_target_part(source_attempt, fighters[target_id], setup_kind)
            target_delta = sanitized_delta.setdefault(target_id, {})
            effects_added = target_delta.setdefault(C.EFFECTS_ADDED, [])
            effects_added.append(
                _setup_effect_payload(
                    effect_name=setup_kind,
                    target_id=target_id,
                    target_part=target_part,
                    fighters=fighters,
                )
            )
            warnings.append(
                _phase2_validation_warning(
                    code=C.WARNING_CODE_P2_MECHANICAL_REPAIR,
                    fighter_id=target_id,
                    field=f"delta.{target_id}.{C.EFFECTS_ADDED}",
                    source=source_id,
                    action="added",
                    reason=f"successful_{setup_kind}_setup_missing_authorized_effect",
                    canonical_part=target_part,
                )
            )
            repaired_sources.append((source_id, target_id, setup_kind))
        self_setup_kind = _attempt_self_setup_kind(source_attempt)
        if self_setup_kind is None:
            continue
        if _fighter_has_effect(fighters[source_id], self_setup_kind) or _delta_has_effect(
            sanitized_delta,
            source_id,
            self_setup_kind,
        ):
            continue
        source_delta = sanitized_delta.setdefault(source_id, {})
        source_effects_added = source_delta.setdefault(C.EFFECTS_ADDED, [])
        source_effects_added.append(
            _setup_effect_payload(
                effect_name=self_setup_kind,
                target_id=source_id,
                target_part=None,
                fighters=fighters,
            )
        )
        warnings.append(
            _phase2_validation_warning(
                code=C.WARNING_CODE_P2_MECHANICAL_REPAIR,
                fighter_id=source_id,
                field=f"delta.{source_id}.{C.EFFECTS_ADDED}",
                source=source_id,
                action="added",
                reason=f"successful_{self_setup_kind}_setup_missing_authorized_effect",
            )
        )
        repaired_sources.append((source_id, source_id, self_setup_kind))
    return warnings, repaired_sources
