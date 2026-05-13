"""Damage and body-part mutation helpers for fighter state."""

from __future__ import annotations

from typing import Any

from .anatomy import BodyPart
from .effects import Effect, mark_effect_fresh
from .engine import constants as C
from .engine.logger import logger


def layer_current_hp(layer: Any) -> int:
    current_hp = getattr(layer, C.CURRENT_HP, None)
    if current_hp is None:
        current_hp = layer.max_hp
        layer.current_hp = current_hp
    return int(current_hp)


def apply_damage_to_layer(layer: Any, damage_amount: int) -> int:
    current_hp = layer_current_hp(layer)
    dealt_to_layer = min(damage_amount, current_hp)
    layer.current_hp = current_hp - dealt_to_layer
    return dealt_to_layer


def part_is_lost(part: BodyPart) -> bool:
    return (
        part.severed
        or part.status in {C.IS_DESTROYED, C.STATUS_SEVERED}
        or all(layer_current_hp(layer) <= 0 for layer in part.layers)
    )


def mark_part_lost_if_depleted(fighter: Any, part_name: str, part: BodyPart) -> None:
    if not part.layers or not all(layer_current_hp(layer) <= 0 for layer in part.layers):
        return
    if part.status in {C.IS_DESTROYED, C.STATUS_SEVERED} or part.severed:
        return
    if part.can_be_severed:
        part.status = C.STATUS_SEVERED
        part.severed = True
        logger.debug("%s:%s has been severed.", fighter.id, part_name)
        fighter.debuffs.append(
            mark_effect_fresh(
                Effect(
                    name=f"{part_name} {C.STATUS_SEVERED}",
                    magnitude=1,
                    ttl=-1,
                    on_apply=f"{part_name} was severed from the body.",
                    on_tick=None,
                    metadata={C.TARGETED_PART: part_name},
                )
            )
        )
        fighter.pain += 20
    else:
        part.status = C.IS_DESTROYED
    logger.debug("%s:%s has been %s.", fighter.id, part_name, part.status)


def apply_damage_to_part(
    fighter: Any,
    part_name: str,
    damage_amount: int,
    damage_type: C.DamageType | str,
) -> None:
    """Apply damage to one body part and its tissue layers."""
    if damage_amount <= 0:
        logger.warning(
            "Ignoring non-positive damage amount %s to %s for fighter %s", damage_amount, part_name, fighter.id
        )
        fighter._update_status_from_invariants()
        return

    resolved_part_name = fighter.normalize_part_name(part_name)
    if resolved_part_name is None:
        logger.warning("Attempted to damage non-existent part: %s for fighter %s", part_name, fighter.id)
        return

    part_name = resolved_part_name
    part = fighter.parts[part_name]
    remaining_damage = damage_amount
    dt = fighter.normalize_damage_type(damage_type)

    if part.severed or part.status == C.IS_DESTROYED:
        logger.debug("Attempted to damage already severed/destroyed part: %s for fighter %s", part_name, fighter.id)
        fighter.pain += damage_amount // 2
        fighter._update_status_from_invariants()
        return

    for layer in part.layers:
        if remaining_damage <= 0:
            break
        dealt_to_layer = apply_damage_to_layer(layer, remaining_damage)
        remaining_damage -= dealt_to_layer
        logger.debug(
            "Dealt %s %s to %s:%s.%s, HP now %s/%s",
            dealt_to_layer,
            dt,
            fighter.id,
            part_name,
            layer.name,
            layer.current_hp,
            layer.max_hp,
        )

    fighter.pain += damage_amount
    mark_part_lost_if_depleted(fighter, part_name, part)
    _apply_damage_type_effect(fighter, part_name, part, damage_amount, dt)
    fighter._update_status_from_invariants()


def _apply_damage_type_effect(
    fighter: Any,
    part_name: str,
    part: BodyPart,
    damage_amount: int,
    damage_type: str,
) -> None:
    if damage_type == C.DamageType.FIRE.value:
        existing_burning = next(
            (
                eff
                for eff in fighter.debuffs
                if eff.name == C.EFFECT_BURNING and eff.metadata.get(C.TARGETED_PART) == part_name
            ),
            None,
        )
        if not existing_burning:
            fighter.debuffs.append(
                mark_effect_fresh(
                    Effect(
                        name=C.EFFECT_BURNING,
                        magnitude=damage_amount / 10,
                        ttl=3,
                        on_apply=f"{part_name} is on fire!",
                        on_tick=f"{part_name} takes burn damage.",
                        metadata={C.TARGETED_PART: part_name},
                    )
                )
            )
            logger.debug("%s:%s is now burning.", fighter.id, part_name)
    elif damage_type in {C.DamageType.PIERCING.value, C.DamageType.SLASHING.value}:
        existing_bleeding = next(
            (
                eff
                for eff in fighter.debuffs
                if eff.name == C.EFFECT_BLEEDING and eff.metadata.get(C.TARGETED_PART) == part_name
            ),
            None,
        )
        if not existing_bleeding and part.bleed_rate > 0:
            fighter.debuffs.append(
                mark_effect_fresh(
                    Effect(
                        name=C.EFFECT_BLEEDING,
                        magnitude=part.bleed_rate * (damage_amount / 10),
                        ttl=5,
                        on_apply=f"{part_name} is bleeding profusely!",
                        on_tick=f"{part_name} loses blood.",
                        metadata={C.TARGETED_PART: part_name},
                    )
                )
            )
            logger.debug("%s:%s is now bleeding.", fighter.id, part_name)
