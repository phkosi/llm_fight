"""Predefined anatomical presets and utility builders."""

from __future__ import annotations

from dataclasses import dataclass, field

from .engine import constants as C

__all__ = ["HUMANOID", "BodyPart", "Preset", "TissueLayer"]


@dataclass
class TissueLayer:
    name: str
    max_hp: int
    current_hp: int | None = None

    def __post_init__(self) -> None:
        if self.current_hp is None:
            self.current_hp = self.max_hp


@dataclass
class BodyPart:
    name: str
    layers: list[TissueLayer]
    severed: bool = False
    status: str = "intact"  # e.g., intact, bruised, broken, destroyed, severed
    is_vital: bool = False  # is this part vital for survival?
    can_be_severed: bool = False  # Can this part be severed (e.g., limbs)?
    bleed_rate: int = 0  # Potential blood loss per tick if bleeding applied to this part
    burn_rate: int = 0  # Potential severity/damage increase if burning applied to this part
    consequence_tags: list[str] = field(default_factory=list)
    consequence_group: str | None = None


@dataclass
class Preset:
    name: str
    parts: dict[str, BodyPart]


# --- Helpers -----------------------------------------------------------


def compose_humanoid() -> Preset:
    def base_layers() -> list[TissueLayer]:
        return [
            TissueLayer("skin", 10),
            TissueLayer("fat", 5),
            TissueLayer("muscle", 15),
            TissueLayer("bone", 10),
        ]

    parts = {
        "head": BodyPart(
            "head",
            base_layers(),
            is_vital=True,
            can_be_severed=False,
            bleed_rate=1,
            burn_rate=1,
            consequence_tags=[C.CONSEQUENCE_FATAL_IF_DESTROYED],
        ),
        "torso": BodyPart(
            "torso",
            [*base_layers(), TissueLayer("organs", 20)],
            is_vital=True,
            can_be_severed=False,
            bleed_rate=2,
            burn_rate=1,
            consequence_tags=[C.CONSEQUENCE_INCAPACITATING_IF_DESTROYED],
        ),
        "left_arm": BodyPart("left_arm", base_layers(), can_be_severed=True, bleed_rate=1, burn_rate=1),
        "right_arm": BodyPart("right_arm", base_layers(), can_be_severed=True, bleed_rate=1, burn_rate=1),
        "left_leg": BodyPart(
            "left_leg",
            base_layers(),
            can_be_severed=True,
            bleed_rate=1,
            burn_rate=1,
            consequence_tags=[C.CONSEQUENCE_MOBILITY_MEMBER],
            consequence_group=C.CONSEQUENCE_GROUP_LEGS,
        ),
        "right_leg": BodyPart(
            "right_leg",
            base_layers(),
            can_be_severed=True,
            bleed_rate=1,
            burn_rate=1,
            consequence_tags=[C.CONSEQUENCE_MOBILITY_MEMBER],
            consequence_group=C.CONSEQUENCE_GROUP_LEGS,
        ),
        "heart": BodyPart(
            "heart",
            [TissueLayer("muscle", 20)],
            is_vital=True,
            can_be_severed=False,
            bleed_rate=3,
            burn_rate=1,
            consequence_tags=[C.CONSEQUENCE_FATAL_IF_DESTROYED],
        ),
        "left_eye": BodyPart(
            "left_eye",
            [TissueLayer("soft", 5)],
            can_be_severed=False,
            consequence_tags=[C.CONSEQUENCE_VISION_MEMBER],
            consequence_group=C.CONSEQUENCE_GROUP_VISION,
        ),  # Eyes probably destroyed, not severed
        "right_eye": BodyPart(
            "right_eye",
            [TissueLayer("soft", 5)],
            can_be_severed=False,
            consequence_tags=[C.CONSEQUENCE_VISION_MEMBER],
            consequence_group=C.CONSEQUENCE_GROUP_VISION,
        ),
    }
    return Preset("humanoid", parts)


HUMANOID = compose_humanoid()

PRESETS = {
    "humanoid": HUMANOID,
}
