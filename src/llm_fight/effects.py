"""Effect payload validation and ticking helpers."""

from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass, field
from typing import Any, cast

from jsonschema import ValidationError, validate

from .engine import constants as C
from .engine.logger import logger
from .rng import choice
from .validation import EffectSchema

_SAFE_EFFECT_NAME_RE = re.compile(C.EFFECT_SAFE_NAME_PATTERN)
_SAFE_EFFECT_TEXT_RE = re.compile(C.EFFECT_SAFE_TEXT_PATTERN)


@dataclass
class Effect:
    """Represents an active buff or debuff affecting a fighter."""

    name: str
    magnitude: float
    ttl: int  # turns remaining (-1 => infinite)
    on_apply: str
    on_tick: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    mechanics: list[dict[str, Any]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    fresh_turns: int = field(default=0, repr=False, compare=False)

    def tick(self):
        """Ticks down the effect's time-to-live. Returns True if expired."""
        if not isinstance(self.ttl, int) or isinstance(self.ttl, bool):
            logger.warning("Expiring effect '%s' with invalid TTL: %r", self.name, self.ttl)
            self.ttl = 0
            return True
        if self.ttl < -1 or self.ttl > C.EFFECT_MAX_TTL:
            logger.warning("Expiring effect '%s' with out-of-bounds TTL: %r", self.name, self.ttl)
            self.ttl = 0
            return True
        if self.ttl > 0:
            self.ttl -= 1
        return self.ttl == 0


def mark_effect_fresh(eff: Effect) -> Effect:
    eff.fresh_turns = 1
    return eff


def _contains_forbidden_effect_text(value: str) -> bool:
    text = value.lower()
    return any(fragment in text for fragment in C.EFFECT_FORBIDDEN_TEXT_FRAGMENTS)


def _safe_effect_tags(fighter: Any, raw_tags: Any) -> list[str] | None:
    if raw_tags is None:
        return []
    if not isinstance(raw_tags, list):
        logger.warning("Rejected effect for %s with non-list tags.", fighter.id)
        return None
    tags: list[str] = []
    for tag in raw_tags:
        if not isinstance(tag, str):
            logger.warning("Rejected effect for %s with non-string tag: %r", fighter.id, tag)
            return None
        normalized = tag.strip().lower().replace("-", "_").replace(" ", "_")
        if (
            not normalized
            or len(normalized) > C.EFFECT_TAG_MAX_LENGTH
            or not _SAFE_EFFECT_NAME_RE.fullmatch(normalized)
            or _contains_forbidden_effect_text(normalized)
        ):
            logger.warning("Rejected effect for %s with unsafe tag: %r", fighter.id, tag)
            return None
        if normalized not in tags:
            tags.append(normalized)
    return tags


def _is_safe_effect_text(fighter: Any, value: Any, *, field_name: str, max_length: int) -> bool:
    if not isinstance(value, str):
        logger.warning("Rejected effect for %s with non-string %s: %r", fighter.id, field_name, value)
        return False
    if not value or len(value) > max_length:
        logger.warning("Rejected effect for %s with invalid %s length.", fighter.id, field_name)
        return False
    if _contains_forbidden_effect_text(value):
        logger.warning("Rejected effect for %s with instruction-like %s.", fighter.id, field_name)
        return False
    if any(ord(char) < 32 for char in value):
        logger.warning("Rejected effect for %s with control characters in %s.", fighter.id, field_name)
        return False
    return True


def _safe_effect_mechanics(fighter: Any, raw_mechanics: Any) -> list[dict[str, Any]] | None:
    if raw_mechanics is None:
        return []
    if not isinstance(raw_mechanics, list):
        logger.warning("Rejected effect for %s with non-list mechanics.", fighter.id)
        return None
    mechanics: list[dict[str, Any]] = []
    for mechanic in raw_mechanics:
        if not isinstance(mechanic, dict):
            logger.warning("Rejected effect for %s with non-object mechanic: %r", fighter.id, mechanic)
            return None
        kind = mechanic.get(C.EFFECT_MECHANIC_KIND)
        normalized = dict(mechanic)
        if kind == C.EFFECT_MECHANIC_DAMAGE_TICK:
            target_part = normalized.get(C.TARGETED_PART)
            resolved_part = fighter.normalize_part_name(cast(str, target_part))
            if resolved_part is None:
                logger.warning(
                    "Rejected effect mechanic for %s with unknown targeted part: %r",
                    fighter.id,
                    target_part,
                )
                return None
            normalized[C.TARGETED_PART] = resolved_part
            normalized[C.TYPE] = fighter.normalize_damage_type(normalized.get(C.TYPE, C.DamageType.GENERIC.value))
        mechanics.append(normalized)
    return mechanics


def build_effect_from_payload(fighter: Any, eff_data: Any) -> tuple[str, Effect] | None:
    if not isinstance(eff_data, dict):
        logger.warning("Rejected non-object effect payload for fighter %s: %r", fighter.id, eff_data)
        return None
    try:
        validate(eff_data, EffectSchema)
    except ValidationError as exc:
        logger.warning("Rejected invalid effect payload for fighter %s: %s", fighter.id, exc.message)
        return None

    effect_name = eff_data[C.NAME].strip()
    if not _SAFE_EFFECT_NAME_RE.fullmatch(effect_name) or _contains_forbidden_effect_text(effect_name):
        logger.warning("Rejected unsafe effect name for fighter %s: %r", fighter.id, effect_name)
        return None

    raw_magnitude = eff_data.get(C.VALUE, eff_data.get("magnitude"))
    if isinstance(raw_magnitude, bool) or not isinstance(raw_magnitude, (int, float)):
        logger.warning("Rejected effect '%s' for fighter %s with invalid magnitude.", effect_name, fighter.id)
        return None
    magnitude = float(raw_magnitude)
    if not math.isfinite(magnitude) or magnitude <= 0 or magnitude > C.EFFECT_MAX_MAGNITUDE:
        logger.warning("Rejected effect '%s' for fighter %s with out-of-bounds magnitude.", effect_name, fighter.id)
        return None

    ttl = eff_data[C.EFFECT_TTL]
    if isinstance(ttl, bool) or not isinstance(ttl, int) or ttl == 0 or ttl < -1 or ttl > C.EFFECT_MAX_TTL:
        logger.warning("Rejected effect '%s' for fighter %s with invalid TTL.", effect_name, fighter.id)
        return None

    on_apply = eff_data.get(C.EFFECT_ON_APPLY, f"{effect_name} applied.")
    if not _SAFE_EFFECT_TEXT_RE.fullmatch(on_apply) or not _is_safe_effect_text(
        fighter,
        on_apply,
        field_name=C.EFFECT_ON_APPLY,
        max_length=C.EFFECT_TEXT_MAX_LENGTH,
    ):
        return None

    on_tick = eff_data.get(C.EFFECT_ON_TICK)
    if on_tick is not None and (
        not _SAFE_EFFECT_TEXT_RE.fullmatch(on_tick)
        or not _is_safe_effect_text(
            fighter,
            on_tick,
            field_name=C.EFFECT_ON_TICK,
            max_length=C.EFFECT_TEXT_MAX_LENGTH,
        )
    ):
        return None

    metadata = dict(eff_data.get(C.METADATA, {}))
    targeted_part = metadata.get(C.TARGETED_PART)
    if targeted_part is not None:
        if not _SAFE_EFFECT_NAME_RE.fullmatch(targeted_part) or not _is_safe_effect_text(
            fighter,
            targeted_part,
            field_name=f"{C.METADATA}.{C.TARGETED_PART}",
            max_length=C.EFFECT_METADATA_VALUE_MAX_LENGTH,
        ):
            return None
        resolved_part = fighter.normalize_part_name(targeted_part)
        if resolved_part is None:
            logger.warning(
                "Rejected effect '%s' for fighter %s with unknown targeted part: %r",
                effect_name,
                fighter.id,
                targeted_part,
            )
            return None
        metadata[C.TARGETED_PART] = resolved_part

    mechanics = _safe_effect_mechanics(fighter, eff_data.get(C.EFFECT_MECHANICS))
    if mechanics is None:
        return None
    tags = _safe_effect_tags(fighter, eff_data.get(C.EFFECT_TAGS))
    if tags is None:
        return None

    list_name = eff_data.get(C.TYPE, C.DEBUFFS)
    return (
        list_name,
        Effect(
            name=effect_name,
            magnitude=magnitude,
            ttl=ttl,
            on_apply=on_apply,
            on_tick=on_tick,
            metadata=metadata,
            mechanics=mechanics,
            tags=tags,
        ),
    )


def safe_effect_removal_selector(fighter: Any, raw_selector: Any) -> dict[str, Any] | None:
    if isinstance(raw_selector, str):
        effect_name = raw_selector.strip()
        selector: dict[str, Any] = {C.NAME: effect_name}
    elif isinstance(raw_selector, dict):
        raw_name = raw_selector.get(C.NAME)
        if not isinstance(raw_name, str):
            logger.warning("Rejected effect removal for %s with missing/non-string name.", fighter.id)
            return None
        effect_name = raw_name.strip()
        selector = {C.NAME: effect_name}
        effect_type = raw_selector.get(C.TYPE)
        if effect_type not in (None, ""):
            if effect_type not in {C.BUFFS, C.DEBUFFS}:
                logger.warning("Rejected effect removal for %s with invalid type: %r", fighter.id, effect_type)
                return None
            selector[C.TYPE] = effect_type
        targeted_part = raw_selector.get(C.TARGETED_PART)
        if targeted_part not in (None, ""):
            if not isinstance(targeted_part, str) or not _SAFE_EFFECT_NAME_RE.fullmatch(targeted_part):
                logger.warning(
                    "Rejected effect removal for %s with unsafe targeted part: %r",
                    fighter.id,
                    targeted_part,
                )
                return None
            resolved_part = fighter.normalize_part_name(targeted_part)
            if resolved_part is None:
                logger.warning(
                    "Rejected effect removal for %s with unknown targeted part: %r",
                    fighter.id,
                    targeted_part,
                )
                return None
            selector[C.TARGETED_PART] = resolved_part
    else:
        logger.warning("Rejected non-string/non-object effect removal for fighter %s: %r", fighter.id, raw_selector)
        return None

    if not _SAFE_EFFECT_NAME_RE.fullmatch(effect_name) or _contains_forbidden_effect_text(effect_name):
        logger.warning("Rejected unsafe effect removal name for fighter %s: %r", fighter.id, effect_name)
        return None
    return selector


def _effect_matches_removal_selector(eff: Effect, selector: dict[str, Any], list_name: str) -> bool:
    if eff.name != selector[C.NAME]:
        return False
    if selector.get(C.TYPE) not in (None, list_name):
        return False
    targeted_part = selector.get(C.TARGETED_PART)
    if targeted_part is not None:
        return eff.metadata.get(C.TARGETED_PART) == targeted_part
    return True


def apply_effect_removal_selector(fighter: Any, selector: dict[str, Any]) -> None:
    for list_name in (C.BUFFS, C.DEBUFFS):
        if selector.get(C.TYPE) not in (None, list_name):
            continue
        effect_list = getattr(fighter, list_name)
        setattr(
            fighter,
            list_name,
            [eff for eff in effect_list if not _effect_matches_removal_selector(eff, selector, list_name)],
        )
    logger.debug("Effect removal selector applied to %s: %r", fighter.id, selector)


def _normalized_effect_magnitude(fighter: Any, eff: Effect) -> float | None:
    magnitude = eff.magnitude
    if isinstance(magnitude, bool) or not isinstance(magnitude, (int, float)):
        logger.warning("Removing effect '%s' on %s with invalid magnitude: %r", eff.name, fighter.id, magnitude)
        return None
    magnitude = float(magnitude)
    if not math.isfinite(magnitude) or magnitude <= 0 or magnitude > C.EFFECT_MAX_MAGNITUDE:
        logger.warning("Removing effect '%s' on %s with out-of-bounds magnitude: %r", eff.name, fighter.id, magnitude)
        return None
    return magnitude


def _has_valid_effect_ttl(fighter: Any, eff: Effect) -> bool:
    ttl = eff.ttl
    if isinstance(ttl, bool) or not isinstance(ttl, int) or ttl == 0 or ttl < -1 or ttl > C.EFFECT_MAX_TTL:
        logger.warning("Removing effect '%s' on %s with invalid TTL before mechanics: %r", eff.name, fighter.id, ttl)
        eff.ttl = 0
        return False
    return True


def _apply_effect_mechanics(fighter: Any, eff: Effect) -> None:
    for mechanic in eff.mechanics:
        kind = mechanic.get(C.EFFECT_MECHANIC_KIND)
        value = mechanic.get(C.VALUE, 1)
        if kind == C.EFFECT_MECHANIC_STAT_TICK:
            stat = mechanic.get(C.EFFECT_MECHANIC_STAT)
            if stat == C.PAIN:
                fighter.pain += int(value)
            elif stat == C.EXHAUSTION:
                fighter.exhaustion += int(value)
            elif stat == C.HEAT:
                fighter.heat += int(value)
        elif kind == C.EFFECT_MECHANIC_DAMAGE_TICK:
            fighter.apply_damage_to_part(
                mechanic[C.TARGETED_PART],
                int(value),
                mechanic.get(C.TYPE, C.DamageType.GENERIC.value),
            )


def apply_effects(fighter: Any, rng: random.Random | None = None) -> None:
    """Apply active effect consequences to a fighter for one tick."""
    for eff_list_name in [C.BUFFS, C.DEBUFFS]:
        eff_list = getattr(fighter, eff_list_name)
        for eff in list(eff_list):
            if not _has_valid_effect_ttl(fighter, eff):
                eff_list.remove(eff)
                continue
            effect_magnitude = _normalized_effect_magnitude(fighter, eff)
            if effect_magnitude is None:
                eff_list.remove(eff)
                continue
            if eff.fresh_turns > 0:
                eff.fresh_turns -= 1
                continue
            if eff.mechanics:
                _apply_effect_mechanics(fighter, eff)
            elif eff.name == C.EFFECT_BURNING:
                _apply_burning_tick(fighter, eff, effect_magnitude, rng)
            elif eff.name == C.EFFECT_BLEEDING:
                _apply_bleeding_tick(fighter, eff, effect_magnitude)

            if eff.on_tick:
                logger.debug(f"Effect tick on {fighter.id}: {eff.on_tick} (Effect: {eff.name}) - TTL: {eff.ttl}")

            expired = eff.tick()
            if expired:
                logger.info(f"Effect {eff.name} on {fighter.id} expired.")
                eff_list.remove(eff)
    fighter._update_status_from_invariants()


def _apply_burning_tick(fighter: Any, eff: Effect, effect_magnitude: float, rng: random.Random | None) -> None:
    fighter.heat += int(effect_magnitude * 5)
    affected_part_name = eff.metadata.get(C.TARGETED_PART)
    if affected_part_name and affected_part_name in fighter.parts:
        target_part = fighter.parts[affected_part_name]
        if target_part.status not in [C.IS_DESTROYED, C.STATUS_SEVERED] and target_part.layers:
            active_layers = [layer for layer in target_part.layers if fighter._layer_current_hp(layer) > 0]
            if active_layers:
                random_layer_to_burn = rng.choice(active_layers) if rng is not None else choice(active_layers)
                burn_damage = max(1, int(effect_magnitude * max(1, target_part.burn_rate)))
                dealt_to_layer = fighter._apply_damage_to_layer(random_layer_to_burn, burn_damage)
                fighter.pain += burn_damage
                fighter._mark_part_lost_if_depleted(affected_part_name, target_part)
                logger.debug(
                    f"{fighter.id} takes {dealt_to_layer} burn damage to "
                    f"{affected_part_name}.{random_layer_to_burn.name} "
                    f"(HP {random_layer_to_burn.current_hp}/{random_layer_to_burn.max_hp}) "
                    f"from '{C.EFFECT_BURNING}' effect."
                )
    else:
        logger.debug(
            f"'{eff.name}' effect on {fighter.id} has no specific target part "
            f"('{affected_part_name}') or target is gone."
        )


def _apply_bleeding_tick(fighter: Any, eff: Effect, effect_magnitude: float) -> None:
    fighter.pain += int(effect_magnitude * 1)
    fighter.exhaustion += int(effect_magnitude * 0.5)
    affected_part_name = eff.metadata.get(C.TARGETED_PART)
    logger.debug(
        f"{fighter.id}'s '{affected_part_name}' is bleeding "
        f"(magnitude {effect_magnitude:.2f}) due to '{C.EFFECT_BLEEDING}' effect."
    )
