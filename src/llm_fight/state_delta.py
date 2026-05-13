"""Judge delta application helpers for fighter state."""

from __future__ import annotations

from typing import Any

from .effects import (
    apply_effect_removal_selector,
    build_effect_from_payload,
    mark_effect_fresh,
    safe_effect_removal_selector,
)
from .engine import constants as C
from .engine.logger import logger


def apply_delta(fighter: Any, delta: dict[str, Any]) -> Any:
    """Apply changes from a Judge P2 delta to one fighter."""
    if not delta:
        fighter._update_status_from_invariants()
        return fighter

    fighter.pain += delta.get(C.PAIN_INCREASE, 0)
    fighter.exhaustion += delta.get(C.EXHAUSTION_INCREASE, 0)
    fighter.heat += delta.get(C.HEAT_INCREASE, 0)

    for wound_data in delta.get(C.WOUNDS, []):
        fighter.apply_damage_to_part(
            part_name=wound_data[C.TARGETED_PART],
            damage_amount=wound_data[C.VALUE],
            damage_type=wound_data.get(C.TYPE, C.DamageType.GENERIC),
        )

    _apply_added_effects(fighter, delta)
    _apply_removed_effects(fighter, delta)

    if C.STATUS_CHANGE in delta:
        fighter._apply_status_change(delta[C.STATUS_CHANGE])

    fighter._update_status_from_invariants()
    return fighter


def _apply_added_effects(fighter: Any, delta: dict[str, Any]) -> None:
    if C.EFFECTS_ADDED not in delta:
        return
    for eff_data in delta[C.EFFECTS_ADDED]:
        parsed_effect = build_effect_from_payload(fighter, eff_data)
        if parsed_effect is None:
            continue
        list_name, new_effect = parsed_effect
        effect_name = new_effect.name

        is_duplicate = False
        for existing_eff_list in (fighter.buffs, fighter.debuffs):
            for eff in existing_eff_list:
                if eff.name == effect_name and eff.ttl == -1:
                    logger.debug(
                        "Prevented adding duplicate permanent effect: %s for fighter %s",
                        effect_name,
                        fighter.id,
                    )
                    is_duplicate = True
                    break
            if is_duplicate:
                break
        if is_duplicate:
            continue

        mark_effect_fresh(new_effect)
        if list_name == C.BUFFS:
            fighter.buffs.append(new_effect)
        else:
            fighter.debuffs.append(new_effect)
        logger.debug(
            "Effect '%s' added to %s. TTL: %s, Magnitude: %.2f",
            new_effect.name,
            fighter.id,
            new_effect.ttl,
            new_effect.magnitude,
        )


def _apply_removed_effects(fighter: Any, delta: dict[str, Any]) -> None:
    if C.EFFECTS_REMOVED not in delta:
        return
    for removal_data in delta[C.EFFECTS_REMOVED]:
        selector = safe_effect_removal_selector(fighter, removal_data)
        if selector is None:
            continue
        apply_effect_removal_selector(fighter, selector)
