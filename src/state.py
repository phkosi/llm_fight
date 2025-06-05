"""Dataclasses representing runtime mutable fighter state."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Literal, Any
import copy # Added import for deepcopy
# import random as rand # This was added by mistake, use project's rng
from .rng import choice  # Use project's seeded RNG

from .anatomy import BodyPart, PRESETS
from .engine import constants as C # Added import
from .engine.logger import logger # Import the logger
from .config import CONFIG

@dataclass
class Effect:
    """Represents an active buff or debuff affecting a fighter."""
    name: str
    magnitude: float
    ttl: int  # turns remaining (-1 => infinite)
    on_apply: str # Description of what happens when applied (for LLM context / logging)
    on_tick: str | None = None # Description of what happens each tick (for LLM context / logging)
    # Actual logic for on_apply and on_tick will be handled in FighterState methods
    metadata: Dict[str, Any] = field(default_factory=dict)

    def tick(self):
        """Ticks down the effect's time-to-live (TTL). Returns True if expired."""
        if self.ttl > 0:
            self.ttl -= 1
        return self.ttl == 0

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
    status: Literal[C.STATUS_FIGHTING, C.STATUS_UNCONSCIOUS, C.STATUS_DEAD] = C.STATUS_FIGHTING # Changed to use constants
    class_: str = "Generic Fighter"
    loadout: str = "their bare fists and wits"
    environment: str = "an open arena"

    @classmethod
    def from_preset(cls, id_: str, preset_name: str) -> FighterState:
        """Creates a FighterState instance from a predefined anatomical preset."""
        preset = PRESETS[preset_name]
        # Use deepcopy so presets aren't mutated across fighters
        parts_copy = copy.deepcopy(preset.parts)

        settings = CONFIG.get_fighter_settings(id_)

        return cls(
            id=id_,
            parts=parts_copy,
            class_=settings['class_'],
            loadout=settings['loadout'],
            environment=settings['environment'],
        )

    # ------------------ utilities --------------------------------------
    def to_json(self) -> Dict[str, Any]:
        """Serializes the fighter's state to a JSON-compatible dictionary."""
        return asdict(self)

    def apply_damage_to_part(self, part_name: str, damage_amount: int, damage_type: str):
        """Applies damage to a specific body part and its tissue layers."""
        if part_name not in self.parts:
            logger.warning(f"Attempted to damage non-existent part: {part_name} for fighter {self.id}") # Replaced print with logger.warning
            return

        part = self.parts[part_name]
        remaining_damage = damage_amount

        # If part is already severed or destroyed, no more damage can be applied to its layers
        if part.severed or part.status == C.IS_DESTROYED:
            logger.debug(f"Attempted to damage already severed/destroyed part: {part_name} for fighter {self.id}") # Replaced print with logger.debug
            # Optionally, apply pain or other effects even if part is gone/destroyed
            self.pain += damage_amount // 2 # Reduced pain for hitting a gone part
            return

        for layer in part.layers:
            if remaining_damage <= 0:
                break
            # Apply damage to layer HP
            dealt_to_layer = min(remaining_damage, layer.max_hp) # Cannot deal more damage than current HP
            layer.max_hp -= dealt_to_layer
            remaining_damage -= dealt_to_layer
            logger.debug(f"Dealt {dealt_to_layer} {damage_type} to {self.id}:{part_name}.{layer.name}, HP now {layer.max_hp}") # Replaced print with logger.debug

        # Basic pain update - can be refined
        self.pain += damage_amount

        # Check for part destruction or severing
        if all(layer.max_hp <= 0 for layer in part.layers):
            if part.can_be_severed: 
                part.status = C.STATUS_SEVERED 
                part.severed = True
                logger.info(f"{self.id}:{part_name} has been severed!") # Replaced print with logger.info
                # Add a generic "SeveredPart" effect or similar if desired
                self.debuffs.append(Effect(name=f"{part_name} {C.STATUS_SEVERED}", magnitude=1, ttl=-1, on_apply=f"{part_name} was severed from the body.", on_tick=None, metadata={C.TARGETED_PART: part_name})) 
                self.pain += 20 # Extra pain for severing
            else:
                part.status = C.IS_DESTROYED 
            logger.info(f"{self.id}:{part_name} has been {part.status}.") # Replaced print with logger.info
            if part.is_vital:
                self.status = C.STATUS_UNCONSCIOUS 

        # Apply bleeding or burning effects based on damage type
        if damage_type == C.DAMAGE_TYPE_FIRE: # Was C.EFFECT_BURNING, changed to C.DAMAGE_TYPE_FIRE for consistency
            existing_burning = next((eff for eff in self.debuffs if eff.name == C.EFFECT_BURNING and eff.metadata.get(C.TARGETED_PART) == part_name), None) 
            if not existing_burning:
                self.debuffs.append(Effect(
                    name=C.EFFECT_BURNING, 
                    magnitude=damage_amount / 10,  
                    ttl=3,  
                    on_apply=f'{part_name} is on fire!',
                    on_tick=f'{part_name} takes burn damage.',
                    metadata={C.TARGETED_PART: part_name} 
                ))
                logger.debug(f"{self.id}:{part_name} is now burning.")
        elif damage_type == C.DAMAGE_TYPE_PIERCING or damage_type == C.DAMAGE_TYPE_SLASHING: # Changed to use constants
            existing_bleeding = next((eff for eff in self.debuffs if eff.name == C.EFFECT_BLEEDING and eff.metadata.get(C.TARGETED_PART) == part_name), None) 
            if not existing_bleeding and part.bleed_rate > 0: 
                 self.debuffs.append(Effect(
                    name=C.EFFECT_BLEEDING, 
                    magnitude=part.bleed_rate * (damage_amount / 10), 
                    ttl=5, 
                    on_apply=f'{part_name} is bleeding profusely!',
                    on_tick=f'{part_name} loses blood.',
                    metadata={C.TARGETED_PART: part_name} 
                ))
                 logger.debug(f"{self.id}:{part_name} is now bleeding.")

    def apply_delta(self, delta: Dict[str, Any]):
        """Applies changes from a Judge P2 delta to the fighter's state."""
        if not delta: 
            return

        self.pain += delta.get(C.PAIN_INCREASE, 0) 
        self.exhaustion += delta.get(C.EXHAUSTION_INCREASE, 0) 
        self.heat += delta.get(C.HEAT_INCREASE, 0) 

        for wound_data in delta.get(C.WOUNDS, []): 
            self.apply_damage_to_part(
                part_name=wound_data[C.TARGETED_PART], 
                damage_amount=wound_data[C.VALUE], 
                damage_type=wound_data.get(C.TYPE, C.DAMAGE_TYPE_GENERIC) # Changed to use constant for default
            )

        if C.EFFECTS_ADDED in delta:
            for eff_data in delta[C.EFFECTS_ADDED]:
                effect_name = eff_data.get(C.NAME) 
                if not effect_name:
                    logger.warning(f"Effect data missing '{C.NAME}' for fighter {self.id}: {eff_data}") # Replaced print with logger.warning
                    continue
                
                is_duplicate = False
                for existing_eff_list in (self.buffs, self.debuffs):
                    for eff in existing_eff_list:
                        if eff.name == effect_name and eff.ttl == -1: 
                            logger.debug(f"Prevented adding duplicate permanent effect: {effect_name} for fighter {self.id}") # Replaced print with logger.debug
                            is_duplicate = True
                            break
                    if is_duplicate: break
                if is_duplicate: continue

                new_effect = Effect(
                    name=effect_name,
                    magnitude=eff_data.get(C.VALUE, 1.0), 
                    ttl=eff_data.get(C.EFFECT_TTL, -1), 
                    on_apply=eff_data.get(C.EFFECT_ON_APPLY, f'{effect_name} applied.'), 
                    on_tick=eff_data.get(C.EFFECT_ON_TICK), 
                    metadata=eff_data.get(C.METADATA, {}) 
                )
                if eff_data.get(C.TYPE, C.DEBUFFS) == C.BUFFS: 
                     self.buffs.append(new_effect)
                else:
                     self.debuffs.append(new_effect)
                logger.info(f"Effect '{new_effect.name}' added to {self.id}. TTL: {new_effect.ttl}, Magnitude: {new_effect.magnitude:.2f}")

        if C.EFFECTS_REMOVED in delta:
            names_to_remove = set(delta[C.EFFECTS_REMOVED]) # Use a set for efficient lookup
            self.buffs = [eff for eff in self.buffs if eff.name not in names_to_remove]
            self.debuffs = [eff for eff in self.debuffs if eff.name not in names_to_remove]
            for name_removed in names_to_remove: # Optional: log removal
                 logger.debug(f"Effect '{name_removed}' removed from {self.id} via delta.")

        if C.STATUS_CHANGE in delta:
            self.status = delta[C.STATUS_CHANGE]

        # Check for status changes due to pain
        if self.pain >= C.MAX_PAIN_THRESHOLD and self.status == C.STATUS_FIGHTING: # Use constant
            logger.info(f"{self.id} fell unconscious due to pain: {self.pain}. Current status: {self.status}") 
            self.status = C.STATUS_UNCONSCIOUS
            logger.info(f"{self.id} status is now {self.status}")
        
        # Check for death by pain AFTER unconsciousness check
        logger.debug(f"Checking death by pain for {self.id}: Pain={self.pain} (Limit={C.MAX_PAIN_BEFORE_DEATH}), Status={self.status}")
        if self.pain >= C.MAX_PAIN_BEFORE_DEATH and self.status != C.STATUS_DEAD :
            logger.info(f"{self.id} met conditions for death by pain. Current status before change: {self.status}")
            self.status = C.STATUS_DEAD
            logger.info(f"{self.id} died from excessive pain: {self.pain}. Status is now {self.status}")
        else:
            logger.debug(f"{self.id} did NOT meet conditions for death by pain.")

        vital_parts_destroyed = 0
        total_vital_parts = 0
        for part in self.parts.values():
            if part.is_vital:
                total_vital_parts += 1
                if part.status == C.IS_DESTROYED: 
                    vital_parts_destroyed +=1
        
        if total_vital_parts > 0 and vital_parts_destroyed == total_vital_parts and self.status != C.STATUS_DEAD:
            self.status = C.STATUS_DEAD 
            logger.info(f"Fighter {self.id} died due to destruction of all vital parts.")
        elif any(p.is_vital and p.status == C.IS_DESTROYED for p in self.parts.values()) and self.status == C.STATUS_FIGHTING:
            self.status = C.STATUS_UNCONSCIOUS 
            logger.info(f"Fighter {self.id} fell unconscious due to destruction of a vital part.")

        return self # Allow chaining or inspection

    def apply_effects(self):
        """Applies the actual consequences of active effects each tick."""
        for eff_list_name in [C.BUFFS, C.DEBUFFS]: 
            eff_list = getattr(self, eff_list_name)
            for eff in list(eff_list): 
                if eff.name == C.EFFECT_BURNING: 
                    # self.pain += int(eff.magnitude * 2) # Removed: Pain is handled by apply_damage_to_part
                    self.heat += int(eff.magnitude * 5)   
                    affected_part_name = eff.metadata.get(C.TARGETED_PART) 
                    if affected_part_name and affected_part_name in self.parts:
                        target_part = self.parts[affected_part_name]
                        if target_part.status not in [C.IS_DESTROYED, C.STATUS_SEVERED] and target_part.layers:
                            active_layers = [layer for layer in target_part.layers if layer.max_hp > 0]
                            if active_layers:
                                random_layer_to_burn = choice(active_layers) # Changed to use rng.choice
                                burn_damage = max(1, int(eff.magnitude)) 
                                logger.debug(f"{self.id} takes {burn_damage} burn damage to {affected_part_name}.{random_layer_to_burn.name} from '{C.EFFECT_BURNING}' effect.") # Replaced print with logger.debug
                                self.apply_damage_to_part(affected_part_name, burn_damage, C.EFFECT_FIRE_FROM_EFFECT)
                    else:
                        logger.debug(f"'{eff.name}' effect on {self.id} has no specific target part ('{affected_part_name}') or target is gone.") # Replaced print with logger.debug

                elif eff.name == C.EFFECT_BLEEDING: 
                    self.pain += int(eff.magnitude * 1) 
                    self.exhaustion += int(eff.magnitude * 0.5) 
                    affected_part_name = eff.metadata.get(C.TARGETED_PART) 
                    logger.debug(f"{self.id}'s '{affected_part_name}' is bleeding (magnitude {eff.magnitude:.2f}) due to '{C.EFFECT_BLEEDING}' effect.") # Replaced print with logger.debug

                if eff.on_tick:
                    logger.debug(f"Effect tick on {self.id}: {eff.on_tick} (Effect: {eff.name}) - TTL: {eff.ttl}") # Replaced print with logger.debug
                
                expired = eff.tick() 
                if expired:
                    logger.info(f"Effect {eff.name} on {self.id} expired.") # Replaced print with logger.info
                    eff_list.remove(eff)
