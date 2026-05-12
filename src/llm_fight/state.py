"""Dataclasses representing runtime mutable fighter state."""

from __future__ import annotations
from dataclasses import dataclass, field, asdict, fields, is_dataclass
import random
from typing import Dict, List, Any
import copy
import math
import re
from jsonschema import ValidationError, validate

from .rng import choice

from .anatomy import BodyPart, PRESETS
from .engine import constants as C
from .engine.logger import logger
from . import config as config_mod
from .profiles import FighterProfile, resolve_fighter_profile
from .validation import EffectSchema

PART_ALIASES = {
    "body": "torso",
    "chest": "torso",
    "core": "torso",
    "abdomen": "torso",
    "stomach": "torso",
    "neck": "head",
    "throat": "head",
    "face": "head",
    "skull": "head",
    "left arm": "left_arm",
    "left-arm": "left_arm",
    "left hand": "left_arm",
    "left-hand": "left_arm",
    "right arm": "right_arm",
    "right-arm": "right_arm",
    "right hand": "right_arm",
    "right-hand": "right_arm",
    "hand": "right_arm",
    "arm": "right_arm",
    "left leg": "left_leg",
    "left-leg": "left_leg",
    "left foot": "left_leg",
    "left-foot": "left_leg",
    "right leg": "right_leg",
    "right-leg": "right_leg",
    "right foot": "right_leg",
    "right-foot": "right_leg",
    "foot": "right_leg",
    "leg": "right_leg",
    "eye": "left_eye",
    "left eye": "left_eye",
    "left-eye": "left_eye",
    "right eye": "right_eye",
    "right-eye": "right_eye",
}


DAMAGE_TYPE_ALIASES = {
    "burn": C.DamageType.FIRE.value,
    "burning": C.DamageType.FIRE.value,
    "cut": C.DamageType.SLASHING.value,
    "slash": C.DamageType.SLASHING.value,
    "stab": C.DamageType.PIERCING.value,
    "poison": C.DamageType.GENERIC.value,
    C.EFFECT_FIRE_FROM_EFFECT: C.DamageType.FIRE.value,
}

_SAFE_EFFECT_NAME_RE = re.compile(C.EFFECT_SAFE_NAME_PATTERN)
_SAFE_EFFECT_TEXT_RE = re.compile(C.EFFECT_SAFE_TEXT_PATTERN)
_STATUS_SEVERITY = {
    C.FighterStatus.FIGHTING: 0,
    C.FighterStatus.UNCONSCIOUS: 1,
    C.FighterStatus.DEAD: 2,
}


@dataclass
class Effect:
    """Represents an active buff or debuff affecting a fighter."""

    name: str
    magnitude: float
    ttl: int  # turns remaining (-1 => infinite)
    on_apply: str  # Description of what happens when applied (for LLM context / logging)
    on_tick: str | None = None  # Description of what happens each tick (for LLM context / logging)
    # Actual logic for on_apply and on_tick will be handled in FighterState methods
    metadata: Dict[str, Any] = field(default_factory=dict)
    mechanics: List[Dict[str, Any]] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    fresh_turns: int = field(default=0, repr=False, compare=False)

    def tick(self):
        """Ticks down the effect's time-to-live (TTL). Returns True if expired."""
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


def _effect_asdict(effect: Effect) -> Dict[str, Any]:
    data = asdict(effect)
    data.pop("fresh_turns", None)
    return data


def _to_public_json(value: Any) -> Any:
    if isinstance(value, Effect):
        return _effect_asdict(value)
    if isinstance(value, list):
        return [_to_public_json(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_public_json(item) for key, item in value.items()}
    if is_dataclass(value):
        return {field.name: _to_public_json(getattr(value, field.name)) for field in fields(value)}
    return value


@dataclass
class FighterState:
    """Represents the complete state of a fighter at any point in combat."""

    id: str
    parts: Dict[str, BodyPart]
    pain: int = 0
    exhaustion: int = 0
    heat: int = 0
    buffs: List[Effect] = field(default_factory=list)
    debuffs: List[Effect] = field(default_factory=list)
    status: C.FighterStatus = C.FighterStatus.FIGHTING
    display_name: str = ""
    class_: str = "Generic Fighter"
    theme: str = ""
    loadout: str = "their bare fists and wits"
    environment: str = "an open arena"
    profile_generation: Dict[str, Any] | None = None

    def __post_init__(self) -> None:
        self.display_name = " ".join(str(self.display_name or "").strip().split()) or self.id

    @classmethod
    def from_preset(
        cls,
        id_: str,
        preset_name: str,
        config_section: str | None = None,
        config=None,
    ) -> FighterState:
        """Creates a FighterState instance from a predefined anatomical preset.

        ``config_section`` specifies which INI section to pull fighter settings
        from. When ``None`` it defaults to ``id_`` for backward compatibility.
        """
        preset = PRESETS[preset_name]
        # Use deepcopy so presets aren't mutated across fighters
        parts_copy = copy.deepcopy(preset.parts)

        section = config_section or id_
        cfg = config or config_mod.CONFIG
        settings = cfg.get_fighter_settings(section, display_name_fallback=id_)

        return cls(
            id=id_,
            parts=parts_copy,
            display_name=settings[C.DISPLAY_NAME],
            class_=settings["class_"],
            theme=settings.get(C.THEME, ""),
            loadout=settings["loadout"],
            environment=settings["environment"],
        )

    @classmethod
    def from_profile(
        cls,
        id_: str,
        profile: FighterProfile,
        config_section: str | None = None,
        config=None,
        allow_config_overrides: bool = True,
        profile_generation: dict[str, Any] | None = None,
    ) -> FighterState:
        """Create fighter state from a validated custom profile."""
        section = config_section or id_
        cfg = config or config_mod.CONFIG
        profile_defaults = {
            "class_": profile.class_,
            C.THEME: profile.theme,
            "loadout": profile.loadout,
            "environment": profile.environment,
        }
        if allow_config_overrides:
            settings = cfg.get_fighter_settings(section, profile_defaults=profile_defaults, display_name_fallback=id_)
        else:
            settings = {
                C.DISPLAY_NAME: cfg.get_fighter_display_name(section, fallback=id_),
                "class_": profile.class_ or cfg.get(C.CONFIG_DEFAULT_FIGHTER, C.CONFIG_FIGHTER_CLASS, str),
                C.THEME: profile.theme or "",
                "loadout": profile.loadout or cfg.get(C.CONFIG_DEFAULT_FIGHTER, C.CONFIG_FIGHTER_LOADOUT, str),
                "environment": profile.environment
                or cfg.get(
                    C.CONFIG_DEFAULTS,
                    C.CONFIG_FIGHTER_ENVIRONMENT,
                    str,
                ),
            }
        return cls(
            id=id_,
            parts=copy.deepcopy(profile.parts),
            display_name=settings[C.DISPLAY_NAME],
            class_=settings["class_"],
            theme=settings.get(C.THEME, ""),
            loadout=settings["loadout"],
            environment=settings["environment"],
            profile_generation=copy.deepcopy(profile_generation),
        )

    @classmethod
    def from_config(cls, id_: str, config_section: str | None = None, config=None) -> FighterState:
        """Create fighter state from the active config's profile or humanoid fallback."""
        section = config_section or id_
        cfg = config or config_mod.CONFIG
        profile = resolve_fighter_profile(section, config=cfg)
        if profile is not None:
            return cls.from_profile(id_, profile, config_section=section, config=cfg)
        if config is None:
            return cls.from_preset(id_, "humanoid", config_section=section)
        return cls.from_preset(id_, "humanoid", config_section=section, config=cfg)

    # ------------------ utilities --------------------------------------
    def to_json(self) -> Dict[str, Any]:
        """Serializes the fighter's state to a JSON-compatible dictionary."""
        return _to_public_json(self)

    def normalize_part_name(self, part_name: str) -> str | None:
        """Return a known body-part key for common natural-language names."""
        if part_name in self.parts:
            return part_name

        raw = str(part_name).strip().lower().strip(".,;:!?")
        normalized = raw.replace("-", "_").replace(" ", "_")
        if normalized in self.parts:
            return normalized

        alias = PART_ALIASES.get(raw) or PART_ALIASES.get(normalized)
        if alias in self.parts:
            logger.debug("Normalized body part '%s' to '%s' for fighter %s", part_name, alias, self.id)
            return alias

        return None

    def _safe_effect_tags(self, raw_tags: Any) -> list[str] | None:
        if raw_tags is None:
            return []
        if not isinstance(raw_tags, list):
            logger.warning("Rejected effect for %s with non-list tags.", self.id)
            return None
        tags: list[str] = []
        for tag in raw_tags:
            if not isinstance(tag, str):
                logger.warning("Rejected effect for %s with non-string tag: %r", self.id, tag)
                return None
            normalized = tag.strip().lower().replace("-", "_").replace(" ", "_")
            if (
                not normalized
                or len(normalized) > C.EFFECT_TAG_MAX_LENGTH
                or not _SAFE_EFFECT_NAME_RE.fullmatch(normalized)
                or self._contains_forbidden_effect_text(normalized)
            ):
                logger.warning("Rejected effect for %s with unsafe tag: %r", self.id, tag)
                return None
            if normalized not in tags:
                tags.append(normalized)
        return tags

    def _safe_effect_removal_selector(self, raw_selector: Any) -> Dict[str, Any] | None:
        if isinstance(raw_selector, str):
            effect_name = raw_selector.strip()
            selector: Dict[str, Any] = {C.NAME: effect_name}
        elif isinstance(raw_selector, dict):
            raw_name = raw_selector.get(C.NAME)
            if not isinstance(raw_name, str):
                logger.warning("Rejected effect removal for %s with missing/non-string name.", self.id)
                return None
            effect_name = raw_name.strip()
            selector = {C.NAME: effect_name}
            effect_type = raw_selector.get(C.TYPE)
            if effect_type not in (None, ""):
                if effect_type not in {C.BUFFS, C.DEBUFFS}:
                    logger.warning("Rejected effect removal for %s with invalid type: %r", self.id, effect_type)
                    return None
                selector[C.TYPE] = effect_type
            targeted_part = raw_selector.get(C.TARGETED_PART)
            if targeted_part not in (None, ""):
                if not isinstance(targeted_part, str) or not _SAFE_EFFECT_NAME_RE.fullmatch(targeted_part):
                    logger.warning(
                        "Rejected effect removal for %s with unsafe targeted part: %r",
                        self.id,
                        targeted_part,
                    )
                    return None
                resolved_part = self.normalize_part_name(targeted_part)
                if resolved_part is None:
                    logger.warning(
                        "Rejected effect removal for %s with unknown targeted part: %r",
                        self.id,
                        targeted_part,
                    )
                    return None
                selector[C.TARGETED_PART] = resolved_part
        else:
            logger.warning("Rejected non-string/non-object effect removal for fighter %s: %r", self.id, raw_selector)
            return None

        if not _SAFE_EFFECT_NAME_RE.fullmatch(effect_name) or self._contains_forbidden_effect_text(effect_name):
            logger.warning("Rejected unsafe effect removal name for fighter %s: %r", self.id, effect_name)
            return None
        return selector

    def _effect_matches_removal_selector(self, eff: Effect, selector: Dict[str, Any], list_name: str) -> bool:
        if eff.name != selector[C.NAME]:
            return False
        if selector.get(C.TYPE) not in (None, list_name):
            return False
        targeted_part = selector.get(C.TARGETED_PART)
        if targeted_part is not None:
            return eff.metadata.get(C.TARGETED_PART) == targeted_part
        return True

    def _apply_effect_removal_selector(self, selector: Dict[str, Any]) -> None:
        for list_name in (C.BUFFS, C.DEBUFFS):
            if selector.get(C.TYPE) not in (None, list_name):
                continue
            effect_list = getattr(self, list_name)
            setattr(
                self,
                list_name,
                [eff for eff in effect_list if not self._effect_matches_removal_selector(eff, selector, list_name)],
            )
        logger.debug("Effect removal selector applied to %s: %r", self.id, selector)

    def _safe_effect_mechanics(self, raw_mechanics: Any) -> list[Dict[str, Any]] | None:
        if raw_mechanics is None:
            return []
        if not isinstance(raw_mechanics, list):
            logger.warning("Rejected effect for %s with non-list mechanics.", self.id)
            return None
        mechanics: list[Dict[str, Any]] = []
        for mechanic in raw_mechanics:
            if not isinstance(mechanic, dict):
                logger.warning("Rejected effect for %s with non-object mechanic: %r", self.id, mechanic)
                return None
            kind = mechanic.get(C.EFFECT_MECHANIC_KIND)
            normalized = dict(mechanic)
            if kind == C.EFFECT_MECHANIC_DAMAGE_TICK:
                target_part = normalized.get(C.TARGETED_PART)
                resolved_part = self.normalize_part_name(target_part)
                if resolved_part is None:
                    logger.warning(
                        "Rejected effect mechanic for %s with unknown targeted part: %r",
                        self.id,
                        target_part,
                    )
                    return None
                normalized[C.TARGETED_PART] = resolved_part
                normalized[C.TYPE] = self.normalize_damage_type(normalized.get(C.TYPE, C.DamageType.GENERIC.value))
            mechanics.append(normalized)
        return mechanics

    def normalize_damage_type(self, damage_type: C.DamageType | str) -> str:
        """Return a known damage type, mapping common LLM aliases."""
        if isinstance(damage_type, C.DamageType):
            return damage_type.value
        normalized = str(damage_type).strip().lower()
        return DAMAGE_TYPE_ALIASES.get(normalized, normalized)

    def _contains_forbidden_effect_text(self, value: str) -> bool:
        text = value.lower()
        return any(fragment in text for fragment in C.EFFECT_FORBIDDEN_TEXT_FRAGMENTS)

    def _is_safe_effect_text(self, value: Any, *, field_name: str, max_length: int) -> bool:
        if not isinstance(value, str):
            logger.warning("Rejected effect for %s with non-string %s: %r", self.id, field_name, value)
            return False
        if not value or len(value) > max_length:
            logger.warning("Rejected effect for %s with invalid %s length.", self.id, field_name)
            return False
        if self._contains_forbidden_effect_text(value):
            logger.warning("Rejected effect for %s with instruction-like %s.", self.id, field_name)
            return False
        if any(ord(char) < 32 for char in value):
            logger.warning("Rejected effect for %s with control characters in %s.", self.id, field_name)
            return False
        return True

    def _build_effect_from_payload(self, eff_data: Any) -> tuple[str, Effect] | None:
        if not isinstance(eff_data, dict):
            logger.warning("Rejected non-object effect payload for fighter %s: %r", self.id, eff_data)
            return None
        try:
            validate(eff_data, EffectSchema)
        except ValidationError as exc:
            logger.warning("Rejected invalid effect payload for fighter %s: %s", self.id, exc.message)
            return None

        effect_name = eff_data[C.NAME].strip()
        if not _SAFE_EFFECT_NAME_RE.fullmatch(effect_name) or self._contains_forbidden_effect_text(effect_name):
            logger.warning("Rejected unsafe effect name for fighter %s: %r", self.id, effect_name)
            return None

        raw_magnitude = eff_data.get(C.VALUE, eff_data.get("magnitude"))
        if isinstance(raw_magnitude, bool) or not isinstance(raw_magnitude, (int, float)):
            logger.warning("Rejected effect '%s' for fighter %s with invalid magnitude.", effect_name, self.id)
            return None
        magnitude = float(raw_magnitude)
        if not math.isfinite(magnitude) or magnitude <= 0 or magnitude > C.EFFECT_MAX_MAGNITUDE:
            logger.warning("Rejected effect '%s' for fighter %s with out-of-bounds magnitude.", effect_name, self.id)
            return None

        ttl = eff_data[C.EFFECT_TTL]
        if isinstance(ttl, bool) or not isinstance(ttl, int) or ttl == 0 or ttl < -1 or ttl > C.EFFECT_MAX_TTL:
            logger.warning("Rejected effect '%s' for fighter %s with invalid TTL.", effect_name, self.id)
            return None

        on_apply = eff_data.get(C.EFFECT_ON_APPLY, f"{effect_name} applied.")
        if not _SAFE_EFFECT_TEXT_RE.fullmatch(on_apply) or not self._is_safe_effect_text(
            on_apply,
            field_name=C.EFFECT_ON_APPLY,
            max_length=C.EFFECT_TEXT_MAX_LENGTH,
        ):
            return None

        on_tick = eff_data.get(C.EFFECT_ON_TICK)
        if on_tick is not None and (
            not _SAFE_EFFECT_TEXT_RE.fullmatch(on_tick)
            or not self._is_safe_effect_text(
                on_tick,
                field_name=C.EFFECT_ON_TICK,
                max_length=C.EFFECT_TEXT_MAX_LENGTH,
            )
        ):
            return None

        metadata = dict(eff_data.get(C.METADATA, {}))
        targeted_part = metadata.get(C.TARGETED_PART)
        if targeted_part is not None:
            if not _SAFE_EFFECT_NAME_RE.fullmatch(targeted_part) or not self._is_safe_effect_text(
                targeted_part,
                field_name=f"{C.METADATA}.{C.TARGETED_PART}",
                max_length=C.EFFECT_METADATA_VALUE_MAX_LENGTH,
            ):
                return None
            resolved_part = self.normalize_part_name(targeted_part)
            if resolved_part is None:
                logger.warning(
                    "Rejected effect '%s' for fighter %s with unknown targeted part: %r",
                    effect_name,
                    self.id,
                    targeted_part,
                )
                return None
            metadata[C.TARGETED_PART] = resolved_part

        mechanics = self._safe_effect_mechanics(eff_data.get(C.EFFECT_MECHANICS))
        if mechanics is None:
            return None
        tags = self._safe_effect_tags(eff_data.get(C.EFFECT_TAGS))
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

    def _normalized_effect_magnitude(self, eff: Effect) -> float | None:
        magnitude = eff.magnitude
        if isinstance(magnitude, bool) or not isinstance(magnitude, (int, float)):
            logger.warning("Removing effect '%s' on %s with invalid magnitude: %r", eff.name, self.id, magnitude)
            return None
        magnitude = float(magnitude)
        if not math.isfinite(magnitude) or magnitude <= 0 or magnitude > C.EFFECT_MAX_MAGNITUDE:
            logger.warning("Removing effect '%s' on %s with out-of-bounds magnitude: %r", eff.name, self.id, magnitude)
            return None
        return magnitude

    def _has_valid_effect_ttl(self, eff: Effect) -> bool:
        ttl = eff.ttl
        if isinstance(ttl, bool) or not isinstance(ttl, int) or ttl == 0 or ttl < -1 or ttl > C.EFFECT_MAX_TTL:
            logger.warning("Removing effect '%s' on %s with invalid TTL before mechanics: %r", eff.name, self.id, ttl)
            eff.ttl = 0
            return False
        return True

    def _mark_effect_fresh(self, eff: Effect) -> Effect:
        eff.fresh_turns = 1
        return eff

    def _layer_current_hp(self, layer) -> int:
        current_hp = getattr(layer, C.CURRENT_HP, None)
        if current_hp is None:
            current_hp = layer.max_hp
            layer.current_hp = current_hp
        return int(current_hp)

    def _apply_damage_to_layer(self, layer, damage_amount: int) -> int:
        current_hp = self._layer_current_hp(layer)
        dealt_to_layer = min(damage_amount, current_hp)
        layer.current_hp = current_hp - dealt_to_layer
        return dealt_to_layer

    def _part_is_lost(self, part: BodyPart) -> bool:
        return (
            part.severed
            or part.status in {C.IS_DESTROYED, C.STATUS_SEVERED}
            or all(self._layer_current_hp(layer) <= 0 for layer in part.layers)
        )

    def _mark_part_lost_if_depleted(self, part_name: str, part: BodyPart) -> None:
        if not part.layers or not all(self._layer_current_hp(layer) <= 0 for layer in part.layers):
            return
        if part.status in {C.IS_DESTROYED, C.STATUS_SEVERED} or part.severed:
            return
        if part.can_be_severed:
            part.status = C.STATUS_SEVERED
            part.severed = True
            logger.info(f"{self.id}:{part_name} has been severed!")
            self.debuffs.append(
                self._mark_effect_fresh(
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
            self.pain += 20
        else:
            part.status = C.IS_DESTROYED
        logger.info(f"{self.id}:{part_name} has been {part.status}.")

    def _remove_debuffs_by_name(self, names: set[str]) -> None:
        if not names:
            return
        self.debuffs = [eff for eff in self.debuffs if eff.name not in names]

    def _add_or_refresh_consequence_debuff(
        self,
        *,
        name: str,
        magnitude: float,
        on_apply: str,
        tags: list[str],
        metadata: dict[str, Any],
    ) -> None:
        existing = next((eff for eff in self.debuffs if eff.name == name), None)
        if existing is not None:
            existing.magnitude = magnitude
            existing.ttl = -1
            existing.on_apply = on_apply
            existing.metadata = metadata
            existing.tags = tags
            return
        self.debuffs.append(
            self._mark_effect_fresh(
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

    def _apply_group_member_consequence(
        self,
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
            for name, part in self.parts.items()
            if tag in getattr(part, C.CONSEQUENCE_TAGS, []) and part.consequence_group == group
        ]
        lost_members = [name for name, part in members if self._part_is_lost(part)]
        if len(lost_members) >= 2:
            self._remove_debuffs_by_name({weak_name})
            self._add_or_refresh_consequence_debuff(
                name=strong_name,
                magnitude=2,
                on_apply=strong_on_apply,
                tags=[C.EFFECT_TAG_ANATOMY_CONSEQUENCE, tag_name],
                metadata={
                    C.CONSEQUENCE_GROUP: group,
                    "affected_parts": sorted(lost_members),
                },
            )
        elif len(lost_members) == 1 and not any(eff.name == strong_name for eff in self.debuffs):
            self._add_or_refresh_consequence_debuff(
                name=weak_name,
                magnitude=1,
                on_apply=weak_on_apply,
                tags=[C.EFFECT_TAG_ANATOMY_CONSEQUENCE, tag_name],
                metadata={
                    C.CONSEQUENCE_GROUP: group,
                    C.TARGETED_PART: lost_members[0],
                },
            )

    def _apply_anatomy_consequences(self) -> None:
        lost_parts = {name: part for name, part in self.parts.items() if self._part_is_lost(part)}

        for part in lost_parts.values():
            tags = getattr(part, C.CONSEQUENCE_TAGS, [])
            if C.CONSEQUENCE_FATAL_IF_DESTROYED in tags:
                self._apply_status_change(C.FighterStatus.DEAD)
            elif C.CONSEQUENCE_INCAPACITATING_IF_DESTROYED in tags:
                self._apply_status_change(C.FighterStatus.UNCONSCIOUS)

        legacy_members = [
            part
            for part in self.parts.values()
            if C.CONSEQUENCE_LEGACY_VITAL_GROUP_MEMBER in getattr(part, C.CONSEQUENCE_TAGS, [])
            and part.consequence_group == C.CONSEQUENCE_GROUP_LEGACY_VITALS
        ]
        if legacy_members and all(self._part_is_lost(part) for part in legacy_members):
            self._apply_status_change(C.FighterStatus.DEAD)

        self._apply_group_member_consequence(
            tag=C.CONSEQUENCE_VISION_MEMBER,
            group=C.CONSEQUENCE_GROUP_VISION,
            weak_name=C.EFFECT_IMPAIRED_VISION,
            strong_name=C.EFFECT_BLINDED,
            weak_on_apply="Vision is impaired after losing one eye.",
            strong_on_apply="Both eyes are destroyed; vision is gone.",
            tag_name=C.EFFECT_TAG_VISION_IMPAIRED,
        )
        self._apply_group_member_consequence(
            tag=C.CONSEQUENCE_MOBILITY_MEMBER,
            group=C.CONSEQUENCE_GROUP_LEGS,
            weak_name=C.EFFECT_IMPAIRED_MOBILITY,
            strong_name=C.EFFECT_GROUNDED,
            weak_on_apply="Mobility is impaired after losing one leg.",
            strong_on_apply="Both legs are destroyed or severed; the fighter is grounded.",
            tag_name=C.EFFECT_TAG_MOBILITY_IMPAIRED,
        )

    def _apply_effect_mechanics(self, eff: Effect) -> None:
        for mechanic in eff.mechanics:
            kind = mechanic.get(C.EFFECT_MECHANIC_KIND)
            value = mechanic.get(C.VALUE, 1)
            if kind == C.EFFECT_MECHANIC_STAT_TICK:
                stat = mechanic.get(C.EFFECT_MECHANIC_STAT)
                if stat == C.PAIN:
                    self.pain += int(value)
                elif stat == C.EXHAUSTION:
                    self.exhaustion += int(value)
                elif stat == C.HEAT:
                    self.heat += int(value)
            elif kind == C.EFFECT_MECHANIC_DAMAGE_TICK:
                self.apply_damage_to_part(
                    mechanic[C.TARGETED_PART],
                    int(value),
                    mechanic.get(C.TYPE, C.DamageType.GENERIC.value),
                )

    def _update_status_from_invariants(self) -> None:
        """Apply status invariants after any state mutation."""
        if self.pain >= C.MAX_PAIN_THRESHOLD and self.status == C.FighterStatus.FIGHTING:
            logger.info(f"{self.id} fell unconscious due to pain: {self.pain}. Current status: {self.status}")
            self.status = C.FighterStatus.UNCONSCIOUS
            logger.info(f"{self.id} status is now {self.status}")

        logger.debug(
            f"Checking death by pain for {self.id}: Pain={self.pain} (Limit={C.MAX_PAIN_BEFORE_DEATH}), Status={self.status}"
        )
        if self.pain >= C.MAX_PAIN_BEFORE_DEATH and self.status != C.FighterStatus.DEAD:
            logger.info(f"{self.id} met conditions for death by pain. Current status before change: {self.status}")
            self.status = C.FighterStatus.DEAD
            logger.info(f"{self.id} died from excessive pain: {self.pain}. Status is now {self.status}")
        else:
            logger.debug(f"{self.id} did NOT meet conditions for death by pain.")

        self._apply_anatomy_consequences()

    def _apply_status_change(self, new_status: Any) -> None:
        if new_status in (None, ""):
            return
        if not isinstance(new_status, C.FighterStatus):
            try:
                new_status = C.FighterStatus(new_status)
            except ValueError:
                logger.warning(f"Unknown status '{new_status}' for fighter {self.id}")
                return

        current_severity = _STATUS_SEVERITY[self.status]
        new_severity = _STATUS_SEVERITY[new_status]
        if new_severity < current_severity:
            logger.warning(
                "Ignoring non-monotonic status change for fighter %s: %s -> %s",
                self.id,
                self.status.value,
                new_status.value,
            )
            return
        self.status = new_status

    def apply_damage_to_part(self, part_name: str, damage_amount: int, damage_type: C.DamageType | str):
        """Applies damage to a specific body part and its tissue layers."""
        if damage_amount <= 0:
            logger.warning(
                "Ignoring non-positive damage amount %s to %s for fighter %s", damage_amount, part_name, self.id
            )
            self._update_status_from_invariants()
            return

        resolved_part_name = self.normalize_part_name(part_name)
        if resolved_part_name is None:
            logger.warning(f"Attempted to damage non-existent part: {part_name} for fighter {self.id}")
            return

        part_name = resolved_part_name
        part = self.parts[part_name]
        remaining_damage = damage_amount
        dt = self.normalize_damage_type(damage_type)

        # If part is already severed or destroyed, no more damage can be applied to its layers
        if part.severed or part.status == C.IS_DESTROYED:
            logger.debug(f"Attempted to damage already severed/destroyed part: {part_name} for fighter {self.id}")
            # Optionally, apply pain or other effects even if part is gone/destroyed
            self.pain += damage_amount // 2  # Reduced pain for hitting a gone part
            self._update_status_from_invariants()
            return

        for layer in part.layers:
            if remaining_damage <= 0:
                break
            dealt_to_layer = self._apply_damage_to_layer(layer, remaining_damage)
            remaining_damage -= dealt_to_layer
            logger.debug(
                f"Dealt {dealt_to_layer} {dt} to {self.id}:{part_name}.{layer.name}, "
                f"HP now {layer.current_hp}/{layer.max_hp}"
            )

        # Basic pain update - can be refined
        self.pain += damage_amount

        # Check for part destruction or severing
        self._mark_part_lost_if_depleted(part_name, part)

        # Apply bleeding or burning effects based on damage type
        if dt == C.DamageType.FIRE.value:
            existing_burning = next(
                (
                    eff
                    for eff in self.debuffs
                    if eff.name == C.EFFECT_BURNING and eff.metadata.get(C.TARGETED_PART) == part_name
                ),
                None,
            )
            if not existing_burning:
                self.debuffs.append(
                    self._mark_effect_fresh(
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
                logger.debug(f"{self.id}:{part_name} is now burning.")
        elif dt in {C.DamageType.PIERCING.value, C.DamageType.SLASHING.value}:
            existing_bleeding = next(
                (
                    eff
                    for eff in self.debuffs
                    if eff.name == C.EFFECT_BLEEDING and eff.metadata.get(C.TARGETED_PART) == part_name
                ),
                None,
            )
            if not existing_bleeding and part.bleed_rate > 0:
                self.debuffs.append(
                    self._mark_effect_fresh(
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
                logger.debug(f"{self.id}:{part_name} is now bleeding.")

        self._update_status_from_invariants()

    def apply_delta(self, delta: Dict[str, Any]):
        """Applies changes from a Judge P2 delta to the fighter's state."""
        if not delta:
            self._update_status_from_invariants()
            return self

        self.pain += delta.get(C.PAIN_INCREASE, 0)
        self.exhaustion += delta.get(C.EXHAUSTION_INCREASE, 0)
        self.heat += delta.get(C.HEAT_INCREASE, 0)

        for wound_data in delta.get(C.WOUNDS, []):
            self.apply_damage_to_part(
                part_name=wound_data[C.TARGETED_PART],
                damage_amount=wound_data[C.VALUE],
                damage_type=wound_data.get(C.TYPE, C.DamageType.GENERIC),
            )

        if C.EFFECTS_ADDED in delta:
            for eff_data in delta[C.EFFECTS_ADDED]:
                parsed_effect = self._build_effect_from_payload(eff_data)
                if parsed_effect is None:
                    continue
                list_name, new_effect = parsed_effect
                effect_name = new_effect.name

                is_duplicate = False
                for existing_eff_list in (self.buffs, self.debuffs):
                    for eff in existing_eff_list:
                        if eff.name == effect_name and eff.ttl == -1:
                            logger.debug(
                                f"Prevented adding duplicate permanent effect: {effect_name} for fighter {self.id}"
                            )
                            is_duplicate = True
                            break
                    if is_duplicate:
                        break
                if is_duplicate:
                    continue

                self._mark_effect_fresh(new_effect)
                if list_name == C.BUFFS:
                    self.buffs.append(new_effect)
                else:
                    self.debuffs.append(new_effect)
                logger.info(
                    f"Effect '{new_effect.name}' added to {self.id}. TTL: {new_effect.ttl}, Magnitude: {new_effect.magnitude:.2f}"
                )

        if C.EFFECTS_REMOVED in delta:
            for removal_data in delta[C.EFFECTS_REMOVED]:
                selector = self._safe_effect_removal_selector(removal_data)
                if selector is None:
                    continue
                self._apply_effect_removal_selector(selector)

        if C.STATUS_CHANGE in delta:
            self._apply_status_change(delta[C.STATUS_CHANGE])

        self._update_status_from_invariants()

        return self  # Allow chaining or inspection

    def apply_effects(self, rng: random.Random | None = None):
        """Applies the actual consequences of active effects each tick."""
        for eff_list_name in [C.BUFFS, C.DEBUFFS]:
            eff_list = getattr(self, eff_list_name)
            for eff in list(eff_list):
                if not self._has_valid_effect_ttl(eff):
                    eff_list.remove(eff)
                    continue
                effect_magnitude = self._normalized_effect_magnitude(eff)
                if effect_magnitude is None:
                    eff_list.remove(eff)
                    continue
                if eff.fresh_turns > 0:
                    eff.fresh_turns -= 1
                    continue
                if eff.mechanics:
                    self._apply_effect_mechanics(eff)
                elif eff.name == C.EFFECT_BURNING:
                    self.heat += int(effect_magnitude * 5)
                    affected_part_name = eff.metadata.get(C.TARGETED_PART)
                    if affected_part_name and affected_part_name in self.parts:
                        target_part = self.parts[affected_part_name]
                        if target_part.status not in [C.IS_DESTROYED, C.STATUS_SEVERED] and target_part.layers:
                            active_layers = [layer for layer in target_part.layers if self._layer_current_hp(layer) > 0]
                            if active_layers:
                                random_layer_to_burn = (
                                    rng.choice(active_layers) if rng is not None else choice(active_layers)
                                )
                                burn_damage = max(1, int(effect_magnitude * max(1, target_part.burn_rate)))
                                dealt_to_layer = self._apply_damage_to_layer(random_layer_to_burn, burn_damage)
                                self.pain += burn_damage
                                self._mark_part_lost_if_depleted(affected_part_name, target_part)
                                logger.debug(
                                    f"{self.id} takes {dealt_to_layer} burn damage to "
                                    f"{affected_part_name}.{random_layer_to_burn.name} "
                                    f"(HP {random_layer_to_burn.current_hp}/{random_layer_to_burn.max_hp}) "
                                    f"from '{C.EFFECT_BURNING}' effect."
                                )
                    else:
                        logger.debug(
                            f"'{eff.name}' effect on {self.id} has no specific target part ('{affected_part_name}') or target is gone."
                        )

                elif eff.name == C.EFFECT_BLEEDING:
                    self.pain += int(effect_magnitude * 1)
                    self.exhaustion += int(effect_magnitude * 0.5)
                    affected_part_name = eff.metadata.get(C.TARGETED_PART)
                    logger.debug(
                        f"{self.id}'s '{affected_part_name}' is bleeding (magnitude {effect_magnitude:.2f}) due to '{C.EFFECT_BLEEDING}' effect."
                    )

                if eff.on_tick:
                    logger.debug(f"Effect tick on {self.id}: {eff.on_tick} (Effect: {eff.name}) - TTL: {eff.ttl}")

                expired = eff.tick()
                if expired:
                    logger.info(f"Effect {eff.name} on {self.id} expired.")
                    eff_list.remove(eff)
        self._update_status_from_invariants()
