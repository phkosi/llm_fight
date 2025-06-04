"""Predefined anatomical presets and utility builders."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List

__all__ = ['TissueLayer', 'BodyPart', 'Preset', 'HUMANOID']

@dataclass
class TissueLayer:
    name: str
    max_hp: int

@dataclass
class BodyPart:
    name: str
    layers: List[TissueLayer]
    severed: bool = False
    status: str = 'intact'  # e.g., intact, bruised, broken, destroyed, severed
    is_vital: bool = False # is this part vital for survival?
    can_be_severed: bool = False # Can this part be severed (e.g., limbs)?
    bleed_rate: int = 0  # Potential blood loss per tick if bleeding applied to this part
    burn_rate: int = 0   # Potential severity/damage increase if burning applied to this part

@dataclass
class Preset:
    name: str
    parts: Dict[str, BodyPart]

# --- Helpers -----------------------------------------------------------

def compose_humanoid() -> Preset:
    base_layers = [
        TissueLayer('skin', 10),
        TissueLayer('fat', 5),
        TissueLayer('muscle', 15),
        TissueLayer('bone', 10),
    ]
    parts = {
        'head': BodyPart('head', base_layers.copy(), is_vital=True, can_be_severed=False),
        'torso': BodyPart('torso', base_layers.copy() + [TissueLayer('organs', 20)], is_vital=True, can_be_severed=False),
        'left_arm': BodyPart('left_arm', base_layers.copy(), can_be_severed=True),
        'right_arm': BodyPart('right_arm', base_layers.copy(), can_be_severed=True),
        'left_leg': BodyPart('left_leg', base_layers.copy(), can_be_severed=True),
        'right_leg': BodyPart('right_leg', base_layers.copy(), can_be_severed=True),
        'heart': BodyPart('heart', [TissueLayer('muscle', 20)], is_vital=True, can_be_severed=False),
        'left_eye': BodyPart('left_eye', [TissueLayer('soft', 5)], can_be_severed=False), # Eyes probably destroyed, not severed
        'right_eye': BodyPart('right_eye', [TissueLayer('soft', 5)], can_be_severed=False),
    }
    return Preset('humanoid', parts)

HUMANOID = compose_humanoid()

PRESETS = {
    'humanoid': HUMANOID,
}
