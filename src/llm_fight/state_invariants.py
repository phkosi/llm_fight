"""Status and anatomy consequence helpers for fighter state."""

from __future__ import annotations

from typing import Any

from .effects import Effect, mark_effect_fresh
from .engine import constants as C
from .engine.logger import logger
from .state_damage import part_is_lost

_STATUS_SEVERITY = {
    C.FighterStatus.FIGHTING: 0,
    C.FighterStatus.UNCONSCIOUS: 1,
    C.FighterStatus.DEAD: 2,
}


def remove_debuffs_by_name(fighter: Any, names: set[str]) -> None:
    if not names:
        return
    fighter.debuffs = [eff for eff in fighter.debuffs if eff.name not in names]


def add_or_refresh_consequence_debuff(
    fighter: Any,
    *,
    name: str,
    magnitude: float,
    on_apply: str,
    tags: list[str],
    metadata: dict[str, Any],
) -> None:
    existing = next((eff for eff in fighter.debuffs if eff.name == name), None)
    if existing is not None:
        existing.magnitude = magnitude
        existing.ttl = -1
        existing.on_apply = on_apply
        existing.metadata = metadata
        existing.tags = tags
        return
    fighter.debuffs.append(
        mark_effect_fresh(
            Effect(
                name=name,
                magnitude=magnitude,
                ttl=-1,
                on_apply=on_apply,
                metadata=metadata,
                tags=tags,
            )
        )
    )


def apply_group_member_consequence(
    fighter: Any,
    *,
    tag: str,
    group: str,
    weak_name: str,
    strong_name: str,
    weak_on_apply: str,
    strong_on_apply: str,
    tag_name: str,
) -> None:
    members = [
        (name, part)
        for name, part in fighter.parts.items()
        if tag in getattr(part, C.CONSEQUENCE_TAGS, []) and part.consequence_group == group
    ]
    lost_members = [name for name, part in members if part_is_lost(part)]
    if len(lost_members) >= 2:
        remove_debuffs_by_name(fighter, {weak_name})
        add_or_refresh_consequence_debuff(
            fighter,
            name=strong_name,
            magnitude=2,
            on_apply=strong_on_apply,
            tags=[C.EFFECT_TAG_ANATOMY_CONSEQUENCE, tag_name],
            metadata={
                C.CONSEQUENCE_GROUP: group,
                "affected_parts": sorted(lost_members),
            },
        )
    elif len(lost_members) == 1 and not any(eff.name == strong_name for eff in fighter.debuffs):
        add_or_refresh_consequence_debuff(
            fighter,
            name=weak_name,
            magnitude=1,
            on_apply=weak_on_apply,
            tags=[C.EFFECT_TAG_ANATOMY_CONSEQUENCE, tag_name],
            metadata={
                C.CONSEQUENCE_GROUP: group,
                C.TARGETED_PART: lost_members[0],
            },
        )


def apply_anatomy_consequences(fighter: Any) -> None:
    lost_parts = {name: part for name, part in fighter.parts.items() if part_is_lost(part)}

    for part in lost_parts.values():
        tags = getattr(part, C.CONSEQUENCE_TAGS, [])
        if C.CONSEQUENCE_FATAL_IF_DESTROYED in tags:
            apply_status_change(fighter, C.FighterStatus.DEAD)
        elif C.CONSEQUENCE_INCAPACITATING_IF_DESTROYED in tags:
            apply_status_change(fighter, C.FighterStatus.UNCONSCIOUS)

    legacy_members = [
        part
        for part in fighter.parts.values()
        if C.CONSEQUENCE_LEGACY_VITAL_GROUP_MEMBER in getattr(part, C.CONSEQUENCE_TAGS, [])
        and part.consequence_group == C.CONSEQUENCE_GROUP_LEGACY_VITALS
    ]
    if legacy_members and all(part_is_lost(part) for part in legacy_members):
        apply_status_change(fighter, C.FighterStatus.DEAD)

    apply_group_member_consequence(
        fighter,
        tag=C.CONSEQUENCE_VISION_MEMBER,
        group=C.CONSEQUENCE_GROUP_VISION,
        weak_name=C.EFFECT_IMPAIRED_VISION,
        strong_name=C.EFFECT_BLINDED,
        weak_on_apply="Vision is impaired after losing one eye.",
        strong_on_apply="Both eyes are destroyed; vision is gone.",
        tag_name=C.EFFECT_TAG_VISION_IMPAIRED,
    )
    apply_group_member_consequence(
        fighter,
        tag=C.CONSEQUENCE_MOBILITY_MEMBER,
        group=C.CONSEQUENCE_GROUP_LEGS,
        weak_name=C.EFFECT_IMPAIRED_MOBILITY,
        strong_name=C.EFFECT_GROUNDED,
        weak_on_apply="Mobility is impaired after losing one leg.",
        strong_on_apply="Both legs are destroyed or severed; the fighter is grounded.",
        tag_name=C.EFFECT_TAG_MOBILITY_IMPAIRED,
    )


def update_status_from_invariants(fighter: Any) -> None:
    """Apply status invariants after any state mutation."""
    if fighter.pain >= C.MAX_PAIN_THRESHOLD and fighter.status == C.FighterStatus.FIGHTING:
        logger.debug(
            "%s fell unconscious due to pain: %s. Current status: %s",
            fighter.id,
            fighter.pain,
            fighter.status,
        )
        fighter.status = C.FighterStatus.UNCONSCIOUS
        logger.debug("%s status is now %s", fighter.id, fighter.status)

    logger.debug(
        "Checking death by pain for %s: Pain=%s (Limit=%s), Status=%s",
        fighter.id,
        fighter.pain,
        C.MAX_PAIN_BEFORE_DEATH,
        fighter.status,
    )
    if fighter.pain >= C.MAX_PAIN_BEFORE_DEATH and fighter.status != C.FighterStatus.DEAD:
        logger.debug(
            "%s met conditions for death by pain. Current status before change: %s",
            fighter.id,
            fighter.status,
        )
        fighter.status = C.FighterStatus.DEAD
        logger.debug("%s died from excessive pain: %s. Status is now %s", fighter.id, fighter.pain, fighter.status)
    else:
        logger.debug("%s did NOT meet conditions for death by pain.", fighter.id)

    apply_anatomy_consequences(fighter)


def apply_status_change(fighter: Any, new_status: Any) -> None:
    if new_status in (None, ""):
        return
    if not isinstance(new_status, C.FighterStatus):
        try:
            new_status = C.FighterStatus(new_status)
        except ValueError:
            logger.warning("Unknown status '%s' for fighter %s", new_status, fighter.id)
            return

    current_severity = _STATUS_SEVERITY[fighter.status]
    new_severity = _STATUS_SEVERITY[new_status]
    if new_severity < current_severity:
        logger.warning(
            "Ignoring non-monotonic status change for fighter %s: %s -> %s",
            fighter.id,
            fighter.status.value,
            new_status.value,
        )
        return
    fighter.status = new_status
