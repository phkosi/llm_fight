"""Text, intent, and target-name helpers for Judge Phase 2 authorization."""

from __future__ import annotations

import re
from typing import Any

from .engine import constants as C
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
    "sword",
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
    if mentioned:
        return mentioned
    for token in re.findall(r"[a-z0-9_-]+", text):
        resolved_token = target_fighter.normalize_part_name(token)
        if resolved_token is not None and not _self_owned_part_mention(text, token, source_fighter):
            mentioned.add(resolved_token)
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
