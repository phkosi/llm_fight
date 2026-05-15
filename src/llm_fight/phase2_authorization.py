"""Judge Phase 2 delta authorization and target sanitization."""

from __future__ import annotations

import math
import re
from typing import Any, cast

from .engine import constants as C
from .engine.logger import logger
from .state import PART_ALIASES, FighterState

_DAMAGE_INTENT_TERMS = {
    "attack",
    "bite",
    "blade",
    "blow",
    "burn",
    "claw",
    "club",
    "cut",
    "dagger",
    "fire",
    "hit",
    "kick",
    "longsword",
    "pierce",
    "punch",
    "shield bash",
    "shoot",
    "slash",
    "smash",
    "stab",
    "strike",
    "swing",
    "thrust",
    "weapon",
    "wound",
}

_SMOKE_DAMAGE_OVERRIDES = {
    "bite",
    "blade",
    "burn",
    "claw",
    "club",
    "cut",
    "dagger",
    "fire",
    "kick",
    "longsword",
    "pierce",
    "punch",
    "shield bash",
    "slash",
    "smash",
    "stab",
    "sword",
    "thrust",
}

_COMMON_BODY_PART_TERMS = {
    "arm",
    "chest",
    "face",
    "hand",
    "head",
    "heart",
    "leg",
    "limb",
    "neck",
    "shield",
    "torso",
}

_SELF_COST_TERMS = {
    "backfire",
    "burn myself",
    "cost",
    "expose myself",
    "overextend",
    "reckless",
    "recoil",
    "sacrifice",
    "self",
    "strain",
}


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


def _contains_phrase(text: str, phrase: str) -> bool:
    pattern = rf"(?<![a-z0-9_]){re.escape(phrase)}(?![a-z0-9_])"
    return re.search(pattern, text) is not None


def _attempt_has_damage_intent(attempt: str) -> bool:
    text = str(attempt or "").lower()
    if "smoke bomb" in text and not any(_contains_phrase(text, term) for term in _SMOKE_DAMAGE_OVERRIDES):
        return False
    return any(_contains_phrase(text, term) for term in _DAMAGE_INTENT_TERMS)


def _attempt_mentions_body_part(attempt: str) -> bool:
    text = str(attempt or "").lower()
    part_terms = _COMMON_BODY_PART_TERMS | set(PART_ALIASES)
    return any(_contains_phrase(text, term) for term in part_terms)


def _attempt_allows_self_wound(attempt: str) -> bool:
    text = str(attempt or "").lower()
    return any(term in text for term in _SELF_COST_TERMS)


def _mentioned_target_parts(attempt: str, target_fighter: FighterState) -> set[str]:
    text = str(attempt or "").lower()
    mentioned = set()
    for part_name in target_fighter.parts:
        variants = _part_variants(part_name)
        if any(_contains_phrase(text, variant.lower()) for variant in variants):
            mentioned.add(part_name)
    if mentioned:
        return mentioned
    for alias in PART_ALIASES:
        resolved_alias = target_fighter.normalize_part_name(alias)
        if resolved_alias is not None and _contains_phrase(text, alias):
            mentioned.add(resolved_alias)
    return mentioned


def _part_variants(part_name: str) -> set[str]:
    return {part_name, part_name.replace("_", " "), part_name.replace("_", "-")}


def _self_owned_part_mention(text: str, variant: str, source_fighter: FighterState) -> bool:
    owner_refs = {
        "my",
        "my own",
        "own",
        f"{source_fighter.id.lower()}'s",
        f"fighter {source_fighter.id.lower()}'s",
        f"{_display_name(source_fighter).lower()}'s",
    }
    return any(
        re.search(rf"(?<![a-z0-9_]){re.escape(owner)}(?:\s+[a-z0-9_-]+){{0,3}}\s+{re.escape(variant)}", text)
        for owner in owner_refs
    )


def _mentioned_opponent_parts(
    attempt: str,
    source_fighter: FighterState,
    target_fighter: FighterState,
) -> set[str]:
    text = str(attempt or "").lower()
    mentioned = set()
    for part_name in target_fighter.parts:
        variants = _part_variants(part_name)
        if any(
            _contains_phrase(text, variant.lower())
            and not _self_owned_part_mention(text, variant.lower(), source_fighter)
            for variant in variants
        ):
            mentioned.add(part_name)
    if mentioned:
        return mentioned
    for alias in PART_ALIASES:
        resolved_alias = target_fighter.normalize_part_name(alias)
        if (
            resolved_alias is not None
            and _contains_phrase(text, alias)
            and not _self_owned_part_mention(text, alias, source_fighter)
        ):
            mentioned.add(resolved_alias)
    return mentioned


def _mentioned_owned_parts(narration: str, owner_fighter: FighterState) -> set[str]:
    text = str(narration or "").lower()
    owner_refs = {
        owner_fighter.id.lower(),
        f"fighter {owner_fighter.id.lower()}",
        _display_name(owner_fighter).lower(),
    }
    mentioned = set()
    for part_name in owner_fighter.parts:
        for variant in _part_variants(part_name):
            if any(
                re.search(
                    rf"(?<![a-z0-9_]){re.escape(owner)}(?:'s)?(?:\s+[a-z0-9_-]+){{0,3}}\s+{re.escape(variant)}",
                    text,
                )
                for owner in owner_refs
            ):
                mentioned.add(part_name)
    return mentioned


def _opponent_id(fighter_id: str) -> str:
    return C.FIGHTER_B if fighter_id == C.FIGHTER_A else C.FIGHTER_A


def _display_name(fighter: FighterState) -> str:
    return fighter.display_name or fighter.id


def _readable_part(part_name: str) -> str:
    return part_name.replace("_", " ")


def _repair_target_part(attempt: str, source_fighter: FighterState, target_fighter: FighterState) -> str | None:
    mentioned_parts = _mentioned_opponent_parts(attempt, source_fighter, target_fighter)
    if len(mentioned_parts) == 1:
        return next(iter(mentioned_parts))
    return None


def _damage_type_from_attempt(attempt: str) -> C.DamageType:
    text = str(attempt or "").lower()
    if any(_contains_phrase(text, term) for term in ("burn", "fire", "flame")):
        return C.DamageType.FIRE
    if any(_contains_phrase(text, term) for term in ("dagger", "pierce", "stab", "thrust")):
        return C.DamageType.PIERCING
    if any(_contains_phrase(text, term) for term in ("blade", "cut", "longsword", "slash", "sword")):
        return C.DamageType.SLASHING
    if any(_contains_phrase(text, term) for term in ("bash", "blow", "club", "kick", "punch", "smash")):
        return C.DamageType.BLUNT
    return C.DamageType.GENERIC


def _attempt_targets_opponent(text: str, target_fighter: FighterState) -> bool:
    refs = {
        "opponent",
        "them",
        "their",
        target_fighter.id.lower(),
        f"fighter {target_fighter.id.lower()}",
        _display_name(target_fighter).lower(),
    }
    return any(_contains_phrase(text, ref) for ref in refs)


def _attempt_setup_kind(attempt: str, target_fighter: FighterState) -> str | None:
    text = str(attempt or "").lower()
    if any(_contains_phrase(text, term) for term in ("smoke", "smoke bomb", "obscure", "disorient", "blind")):
        return "obscured"
    if any(_contains_phrase(text, term) for term in ("flank", "flanked")):
        return "flanked"
    if _attempt_targets_opponent(text, target_fighter) and any(
        _contains_phrase(text, term) for term in ("behind", "position")
    ):
        return "flanked"
    return None


def _attempt_self_setup_kind(attempt: str) -> str | None:
    text = str(attempt or "").lower()
    if any(
        _contains_phrase(text, term)
        for term in (
            "brace",
            "defensive",
            "guard",
            "raise my shield",
            "shield up",
            "stabilize",
            "step back",
            "create distance",
            "take cover",
        )
    ):
        return "guarded"
    return None


def _setup_target_part(attempt: str, target_fighter: FighterState, setup_kind: str) -> str | None:
    if setup_kind != "obscured":
        return None
    text = str(attempt or "").lower()
    for raw_part in ("left_eye", "right_eye", "eye", "eyes", "face", "head"):
        normalized = target_fighter.normalize_part_name(raw_part.rstrip("s"))
        if normalized is not None and _contains_phrase(text, raw_part.replace("_", " ")):
            return normalized
    if any(_contains_phrase(text, term) for term in ("vision", "sight")):
        return target_fighter.normalize_part_name("head")
    return None


def _wound_type_supported_by_attempt(wound: dict[str, Any], attempt: str) -> bool:
    text = str(attempt or "").lower()
    raw_type = wound.get(C.TYPE, C.DamageType.GENERIC)
    damage_type = raw_type.value if isinstance(raw_type, C.DamageType) else str(raw_type).strip().lower()
    if damage_type == C.DamageType.FIRE.value:
        return any(_contains_phrase(text, term) for term in ("burn", "fire", "flame", "ignite", "torch"))
    return True


def _sanitize_phase2_narration(sanitized: dict[str, Any], warnings: list[dict[str, Any]]) -> None:
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

    authorized_delta: dict[str, Any] = {}
    warnings: list[dict[str, Any]] = []
    wound_sources: set[str] = set()
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

    wounds = []
    for index, wound in enumerate(delta.get(C.WOUNDS, [])):
        if _is_authorized_consequence(wound, authorized_sources, C.WOUNDS):
            source = wound.get(C.SOURCE)
            field = f"delta.{fighter_id}.{C.WOUNDS}[{index}]"
            source_attempt = (attempts or {}).get(str(source), "")
            source_fighter = fighters.get(str(source))
            if source_attempt and source == fighter_id and not _attempt_allows_self_wound(source_attempt):
                warnings.append(
                    _phase2_validation_warning(
                        code=C.WARNING_CODE_P2_WOUND_SOURCE_MISMATCH,
                        fighter_id=fighter_id,
                        field=field,
                        source=source,
                        action="dropped",
                        reason="source_attempt_did_not_describe_self_wound",
                    )
                )
                continue
            if source_attempt and not _attempt_has_damage_intent(source_attempt):
                warnings.append(
                    _phase2_validation_warning(
                        code=C.WARNING_CODE_P2_WOUND_WITHOUT_DAMAGE_INTENT,
                        fighter_id=fighter_id,
                        field=field,
                        source=source,
                        action="dropped",
                        reason="source_attempt_did_not_describe_damage",
                    )
                )
                continue
            canonical_part, warning = _resolve_phase2_wound_target(wound, target_fighter, fighter_id, index)
            if warning is not None:
                warnings.append(warning)
                continue
            if source_attempt and not _wound_type_supported_by_attempt(wound, source_attempt):
                warnings.append(
                    _phase2_validation_warning(
                        code=C.WARNING_CODE_P2_WOUND_TYPE_MISMATCH,
                        fighter_id=fighter_id,
                        field=f"{field}.{C.TYPE}",
                        source=source,
                        action="dropped",
                        reason="source_attempt_did_not_support_damage_type",
                    )
                )
                continue

            if source_attempt and source_fighter is not None:
                mentioned_parts = _mentioned_opponent_parts(source_attempt, source_fighter, target_fighter)
            else:
                mentioned_parts = _mentioned_target_parts(source_attempt, target_fighter) if source_attempt else set()
            if mentioned_parts and canonical_part not in mentioned_parts:
                if len(mentioned_parts) == 1:
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
                else:
                    warnings.append(
                        _phase2_validation_warning(
                            code=C.WARNING_CODE_P2_WOUND_TARGET_MISMATCH,
                            fighter_id=fighter_id,
                            field=f"{field}.{C.TARGETED_PART}",
                            source=source,
                            action="dropped",
                            reason="source_attempt_named_different_targets",
                        )
                    )
                    continue

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
            if source in {C.FIGHTER_A, C.FIGHTER_B}:
                wound_sources.add(source)
    if wounds:
        authorized_delta[C.WOUNDS] = wounds

    effects_added = []
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

    return authorized_delta, warnings, wound_sources


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
    wound_sources_by_target: dict[str, set[str]] = {}
    narration = str(sanitized.get(C.NARRATION, ""))
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

    damage_sources = _successful_damage_sources(authorized_sources, attempts, fighters)
    repair_warnings, repaired_sources = _repair_missing_successful_damage(
        sanitized_delta=sanitized_delta,
        wound_sources_by_target=wound_sources_by_target,
        damage_sources=damage_sources,
        attempts=attempts,
    )
    setup_repair_warnings, repaired_setups = _repair_missing_successful_setup(
        sanitized_delta=sanitized_delta,
        authorized_sources=authorized_sources,
        attempts=attempts,
        fighters=fighters,
    )
    if repaired_sources or repaired_setups:
        metadata = sanitized.setdefault(C.METADATA, {})
        if isinstance(metadata, dict):
            metadata[C.P2_ENGINE_REPAIR_USED] = True
        sanitized[C.FIGHT_END] = False
        sanitized[C.WINNER] = None

    sanitized[C.DELTA] = sanitized_delta
    warnings = _merge_phase2_warnings(warnings, invalid_target_warnings, repair_warnings, setup_repair_warnings)
    if warnings:
        sanitized[C.VALIDATION_WARNINGS] = warnings
        _sanitize_phase2_narration(sanitized, warnings)
    if repaired_sources or repaired_setups:
        sanitized[C.NARRATION] = _mechanical_resolution_narration(damage_sources, repaired_setups, fighters)
    elif attempts is not None:
        mismatched_sources = [
            source_id
            for source_id, _, _ in damage_sources
            if _narration_has_failure_for_source(str(sanitized.get(C.NARRATION, "")), source_id, fighters[source_id])
        ]
        if mismatched_sources:
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
    terminal_suppression_warning_codes = {
        C.WARNING_CODE_INVALID_P2_WOUND_TARGET,
        C.WARNING_CODE_INVALID_EFFECT_REMOVAL_TARGET,
        C.WARNING_CODE_P2_WOUND_SOURCE_MISMATCH,
        C.WARNING_CODE_P2_WOUND_TARGET_MISMATCH,
        C.WARNING_CODE_P2_WOUND_WITHOUT_DAMAGE_INTENT,
        C.WARNING_CODE_P2_WOUND_TYPE_MISMATCH,
        C.WARNING_CODE_INVALID_EFFECT_PAYLOAD,
        C.WARNING_CODE_P2_EFFECT_SOURCE_MISMATCH,
    }
    if not sanitized_delta and any(warning.get("code") in terminal_suppression_warning_codes for warning in warnings):
        sanitized[C.FIGHT_END] = False
        sanitized[C.WINNER] = None
    return sanitized
