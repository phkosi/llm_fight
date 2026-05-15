"""Dataclasses representing runtime mutable fighter state."""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from typing import Any

from . import config as config_mod
from . import state_damage, state_delta, state_invariants
from .anatomy import PRESETS, BodyPart
from .effects import (
    Effect,
)
from .effects import (
    apply_effects as apply_effects_to_fighter,
)
from .engine import constants as C
from .engine.logger import logger
from .profiles import FighterProfile, resolve_fighter_profile

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
    "cut": C.DamageType.SLASHING.value,
    "slash": C.DamageType.SLASHING.value,
    "stab": C.DamageType.PIERCING.value,
    "poison": C.DamageType.GENERIC.value,
    C.EFFECT_FIRE_FROM_EFFECT: C.DamageType.FIRE.value,
}


def _effect_asdict(effect: Effect) -> dict[str, Any]:
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
    parts: dict[str, BodyPart]
    pain: int = 0
    exhaustion: int = 0
    heat: int = 0
    buffs: list[Effect] = field(default_factory=list)
    debuffs: list[Effect] = field(default_factory=list)
    status: C.FighterStatus = C.FighterStatus.FIGHTING
    display_name: str = ""
    class_: str = "Generic Fighter"
    theme: str = ""
    loadout: str = "their bare fists and wits"
    environment: str = "an open arena"
    profile_generation: dict[str, Any] | None = None

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
    def to_json(self) -> dict[str, Any]:
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

        raw_tokens = {token for token in normalized.split("_") if token}
        if raw_tokens:
            matches = [
                known_part
                for known_part in self.parts
                if raw_tokens <= {token for token in known_part.lower().replace("-", "_").split("_") if token}
            ]
            if len(matches) == 1:
                logger.debug("Normalized body part '%s' to '%s' for fighter %s", part_name, matches[0], self.id)
                return matches[0]

        return None

    def normalize_damage_type(self, damage_type: C.DamageType | str) -> str:
        """Return a known damage type, mapping common LLM aliases."""
        if isinstance(damage_type, C.DamageType):
            return damage_type.value
        normalized = str(damage_type).strip().lower()
        return DAMAGE_TYPE_ALIASES.get(normalized, normalized)

    def _layer_current_hp(self, layer) -> int:
        return state_damage.layer_current_hp(layer)

    def _apply_damage_to_layer(self, layer, damage_amount: int) -> int:
        return state_damage.apply_damage_to_layer(layer, damage_amount)

    def _part_is_lost(self, part: BodyPart) -> bool:
        return state_damage.part_is_lost(part)

    def _mark_part_lost_if_depleted(self, part_name: str, part: BodyPart) -> None:
        state_damage.mark_part_lost_if_depleted(self, part_name, part)

    def _remove_debuffs_by_name(self, names: set[str]) -> None:
        state_invariants.remove_debuffs_by_name(self, names)

    def _add_or_refresh_consequence_debuff(
        self,
        *,
        name: str,
        magnitude: float,
        on_apply: str,
        tags: list[str],
        metadata: dict[str, Any],
    ) -> None:
        state_invariants.add_or_refresh_consequence_debuff(
            self,
            name=name,
            magnitude=magnitude,
            on_apply=on_apply,
            tags=tags,
            metadata=metadata,
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
        state_invariants.apply_group_member_consequence(
            self,
            tag=tag,
            group=group,
            weak_name=weak_name,
            strong_name=strong_name,
            weak_on_apply=weak_on_apply,
            strong_on_apply=strong_on_apply,
            tag_name=tag_name,
        )

    def _apply_anatomy_consequences(self) -> None:
        state_invariants.apply_anatomy_consequences(self)

    def _update_status_from_invariants(self) -> None:
        state_invariants.update_status_from_invariants(self)

    def _apply_status_change(self, new_status: Any) -> None:
        state_invariants.apply_status_change(self, new_status)

    def apply_damage_to_part(self, part_name: str, damage_amount: int, damage_type: C.DamageType | str):
        """Applies damage to a specific body part and its tissue layers."""
        state_damage.apply_damage_to_part(self, part_name, damage_amount, damage_type)

    def apply_delta(self, delta: dict[str, Any]):
        """Applies changes from a Judge P2 delta to the fighter's state."""
        return state_delta.apply_delta(self, delta)

    def apply_effects(self, rng=None):
        """Applies the actual consequences of active effects each tick."""
        apply_effects_to_fighter(self, rng)
