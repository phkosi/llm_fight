import pytest
from src.state import FighterState, Effect

# PRESETS import ensures presets are loaded when FighterState.from_preset runs
from src.engine import constants as C


# Fixture to create a fresh humanoid fighter state for each test
@pytest.fixture
def humanoid_fighter():
    # Ensure PRESETS is available or FighterState.from_preset can access it
    return FighterState.from_preset("TestFighter", "humanoid")


def test_apply_damage_to_part_reduces_hp(humanoid_fighter: FighterState):
    fighter = humanoid_fighter
    part_name = "left_arm"
    initial_hp_sum = sum(layer.max_hp for layer in fighter.parts[part_name].layers)

    fighter.apply_damage_to_part(part_name, 10, C.DAMAGE_TYPE_SLASHING)

    final_hp_sum = sum(layer.max_hp for layer in fighter.parts[part_name].layers)
    assert final_hp_sum < initial_hp_sum
    assert final_hp_sum == initial_hp_sum - 10, f"Expected HP to be {initial_hp_sum - 10}, but got {final_hp_sum}"
    assert fighter.pain == 10, f"Expected pain to be 10, but got {fighter.pain}"  # Basic pain check


def test_apply_damage_destroys_part(humanoid_fighter: FighterState):
    fighter = humanoid_fighter
    part_name = "left_eye"  # A small part that's easy to destroy

    total_eye_hp = sum(layer.max_hp for layer in fighter.parts[part_name].layers)

    fighter.apply_damage_to_part(part_name, total_eye_hp + 5, C.DAMAGE_TYPE_PIERCING)  # Overkill

    assert fighter.parts[part_name].status == C.IS_DESTROYED
    assert all(layer.max_hp <= 0 for layer in fighter.parts[part_name].layers)
    assert fighter.pain >= total_eye_hp


def test_apply_damage_severs_part(humanoid_fighter: FighterState):
    fighter = humanoid_fighter
    part_name = "left_arm"

    total_arm_hp = sum(layer.max_hp for layer in fighter.parts[part_name].layers)

    fighter.apply_damage_to_part(part_name, total_arm_hp + 10, C.DAMAGE_TYPE_SLASHING)  # Overkill to ensure severing

    assert fighter.parts[part_name].severed is True
    assert fighter.parts[part_name].status == C.STATUS_SEVERED
    assert any(eff.name == f"{part_name} {C.STATUS_SEVERED}" for eff in fighter.debuffs)
    assert fighter.pain >= total_arm_hp + 20


def test_apply_damage_to_severed_part_no_layer_damage(humanoid_fighter: FighterState):
    fighter = humanoid_fighter
    part_name = "left_arm"
    total_arm_hp = sum(layer.max_hp for layer in fighter.parts[part_name].layers)

    fighter.apply_damage_to_part(part_name, total_arm_hp + 10, C.DAMAGE_TYPE_SLASHING)
    assert fighter.parts[part_name].severed is True

    hp_after_sever = [layer.max_hp for layer in fighter.parts[part_name].layers]
    initial_pain_after_sever = fighter.pain

    fighter.apply_damage_to_part(part_name, 20, C.DAMAGE_TYPE_SLASHING)

    hp_after_second_hit = [layer.max_hp for layer in fighter.parts[part_name].layers]

    assert hp_after_second_hit == hp_after_sever
    assert fighter.pain == initial_pain_after_sever + (20 // 2)


def test_apply_fire_damage_adds_burning_effect(humanoid_fighter: FighterState):
    fighter = humanoid_fighter
    part_name = "torso"

    assert not any(
        eff.name == C.EFFECT_BURNING and eff.metadata.get(C.TARGETED_PART) == part_name for eff in fighter.debuffs
    )
    fighter.apply_damage_to_part(part_name, 15, C.DAMAGE_TYPE_FIRE)

    burning_effects = [
        eff
        for eff in fighter.debuffs
        if eff.name == C.EFFECT_BURNING and eff.metadata.get(C.TARGETED_PART) == part_name
    ]
    assert len(burning_effects) == 1
    assert burning_effects[0].magnitude == 1.5  # 15 / 10
    assert burning_effects[0].ttl == 3


def test_apply_piercing_damage_adds_bleeding_effect(humanoid_fighter: FighterState):
    fighter = humanoid_fighter
    part_name = "left_leg"
    fighter.parts[part_name].bleed_rate = 1

    assert not any(
        eff.name == C.EFFECT_BLEEDING and eff.metadata.get(C.TARGETED_PART) == part_name for eff in fighter.debuffs
    )
    fighter.apply_damage_to_part(part_name, 10, C.DAMAGE_TYPE_PIERCING)

    bleeding_effects = [
        eff
        for eff in fighter.debuffs
        if eff.name == C.EFFECT_BLEEDING and eff.metadata.get(C.TARGETED_PART) == part_name
    ]
    assert len(bleeding_effects) == 1
    assert bleeding_effects[0].magnitude == 1.0  # bleed_rate * (10/10) = 1 * 1
    assert bleeding_effects[0].ttl == 5


def test_apply_slashing_damage_adds_bleeding_effect(humanoid_fighter: FighterState):
    fighter = humanoid_fighter
    part_name = "right_arm"
    fighter.parts[part_name].bleed_rate = 2  # Ensure bleed_rate is set for test

    assert not any(
        eff.name == C.EFFECT_BLEEDING and eff.metadata.get(C.TARGETED_PART) == part_name for eff in fighter.debuffs
    )
    fighter.apply_damage_to_part(part_name, 12, C.DAMAGE_TYPE_SLASHING)

    bleeding_effects = [
        eff
        for eff in fighter.debuffs
        if eff.name == C.EFFECT_BLEEDING and eff.metadata.get(C.TARGETED_PART) == part_name
    ]
    assert len(bleeding_effects) == 1
    assert bleeding_effects[0].magnitude == fighter.parts[part_name].bleed_rate * (12 / 10)  # 2 * 1.2 = 2.4
    assert bleeding_effects[0].ttl == 5


def test_apply_damage_to_non_existent_part(humanoid_fighter: FighterState):
    fighter = humanoid_fighter
    initial_pain = fighter.pain
    initial_debuff_count = len(fighter.debuffs)

    # No exception should be raised, and a warning should be logged (checked manually or via log capture if set up)
    fighter.apply_damage_to_part("non_existent_horn", 30, C.DAMAGE_TYPE_GENERIC)

    assert fighter.pain == initial_pain  # Pain should not change if part doesn't exist
    assert len(fighter.debuffs) == initial_debuff_count  # No new effects


def test_vital_part_destruction_leads_to_unconscious(humanoid_fighter: FighterState):
    fighter = humanoid_fighter
    part_name = "head"  # Head is vital
    assert fighter.parts[part_name].is_vital
    assert fighter.status == C.STATUS_FIGHTING

    total_head_hp = sum(layer.max_hp for layer in fighter.parts[part_name].layers)
    fighter.apply_damage_to_part(part_name, total_head_hp + 5, C.DAMAGE_TYPE_PIERCING)  # Destroy the head

    assert fighter.parts[part_name].status == C.IS_DESTROYED
    assert fighter.status == C.STATUS_UNCONSCIOUS


def test_effect_tick_reduces_ttl_and_expires():
    effect = Effect(name="TestEffect", magnitude=1.0, ttl=3, on_apply="Applied", on_tick="Ticks")
    assert effect.ttl == 3

    assert effect.tick() is False  # Tick 1
    assert effect.ttl == 2

    assert effect.tick() is False  # Tick 2
    assert effect.ttl == 1

    assert effect.tick() is True  # Tick 3 - expires
    assert effect.ttl == 0

    assert effect.tick() is True  # Tick 4 - already expired
    assert effect.ttl == 0


def test_infinite_effect_ttl_does_not_change():
    effect = Effect(name="InfiniteEffect", magnitude=1.0, ttl=-1, on_apply="Applied", on_tick="Ticks")
    assert effect.ttl == -1
    assert effect.tick() is False  # Should not expire
    assert effect.ttl == -1


def test_apply_delta_basic_stat_increases(humanoid_fighter: FighterState):
    fighter = humanoid_fighter
    delta = {C.PAIN_INCREASE: 10, C.EXHAUSTION_INCREASE: 5, C.HEAT_INCREASE: 3}
    fighter.apply_delta(delta)
    assert fighter.pain == 10
    assert fighter.exhaustion == 5
    assert fighter.heat == 3


def test_apply_delta_applies_wounds(humanoid_fighter: FighterState):
    fighter = humanoid_fighter
    part_name = "torso"
    initial_hp_sum = sum(layer.max_hp for layer in fighter.parts[part_name].layers)
    damage_val = 15
    delta = {C.WOUNDS: [{C.TARGETED_PART: part_name, C.VALUE: damage_val, C.TYPE: C.DAMAGE_TYPE_PIERCING}]}
    fighter.apply_delta(delta)
    final_hp_sum = sum(layer.max_hp for layer in fighter.parts[part_name].layers)
    assert final_hp_sum == initial_hp_sum - damage_val
    assert fighter.pain == damage_val  # From apply_damage_to_part


def test_apply_delta_adds_new_effect(humanoid_fighter: FighterState):
    fighter = humanoid_fighter
    effect_name = "SuperStrength"
    delta = {
        C.EFFECTS_ADDED: [
            {C.NAME: effect_name, C.VALUE: 2.0, C.EFFECT_TTL: 5, C.TYPE: C.BUFFS, C.EFFECT_ON_APPLY: "Feeling strong!"}
        ]
    }
    fighter.apply_delta(delta)
    assert len(fighter.buffs) == 1
    assert fighter.buffs[0].name == effect_name
    assert fighter.buffs[0].magnitude == 2.0
    assert fighter.buffs[0].ttl == 5


def test_apply_delta_adds_permanent_effect_once(humanoid_fighter: FighterState):
    fighter = humanoid_fighter
    effect_name = "PermanentWeakness"
    effect_data = {C.NAME: effect_name, C.EFFECT_TTL: -1, C.TYPE: C.DEBUFFS}  # TTL -1 for permanent
    delta1 = {C.EFFECTS_ADDED: [effect_data]}
    delta2 = {C.EFFECTS_ADDED: [effect_data]}  # Identical delta

    fighter.apply_delta(delta1)
    assert len(fighter.debuffs) == 1
    assert fighter.debuffs[0].name == effect_name

    # Try applying the same permanent effect again
    fighter.apply_delta(delta2)
    assert len(fighter.debuffs) == 1  # Should not add a duplicate permanent effect


def test_apply_delta_changes_status(humanoid_fighter: FighterState):
    fighter = humanoid_fighter
    delta = {C.STATUS_CHANGE: C.STATUS_UNCONSCIOUS}
    assert fighter.status == C.STATUS_FIGHTING
    fighter.apply_delta(delta)
    assert fighter.status == C.STATUS_UNCONSCIOUS


def test_apply_delta_pain_induces_unconsciousness(humanoid_fighter: FighterState):
    fighter = humanoid_fighter
    assert fighter.status == C.STATUS_FIGHTING
    # Delta that doesn't directly change status but increases pain to >= 100
    delta = {C.PAIN_INCREASE: 100}
    fighter.apply_delta(delta)
    assert fighter.pain >= 100
    assert fighter.status == C.STATUS_UNCONSCIOUS


def test_apply_effects_burning_damages_part_and_increases_stats(humanoid_fighter: FighterState):
    fighter = humanoid_fighter
    part_name = "torso"
    # Add a burning effect directly to the fighter for testing apply_effects
    burning_effect = Effect(
        name=C.EFFECT_BURNING,
        magnitude=2.0,
        ttl=1,
        on_apply="Torso is burning!",
        on_tick="Torso takes burn damage.",
        metadata={C.TARGETED_PART: part_name},
    )
    fighter.debuffs.append(burning_effect)

    initial_pain = fighter.pain
    initial_heat = fighter.heat
    initial_part_hp = sum(layer.max_hp for layer in fighter.parts[part_name].layers)

    fighter.apply_effects()

    expected_burn_damage = max(1, int(burning_effect.magnitude))
    assert fighter.pain == initial_pain + expected_burn_damage  # Corrected expected pain
    assert fighter.heat == initial_heat + int(burning_effect.magnitude * 5)

    final_part_hp = sum(layer.max_hp for layer in fighter.parts[part_name].layers)
    assert final_part_hp == initial_part_hp - expected_burn_damage

    assert not any(eff.name == C.EFFECT_BURNING for eff in fighter.debuffs)


def test_apply_effects_burning_no_specific_target_part(humanoid_fighter: FighterState):
    fighter = humanoid_fighter
    # Add a burning effect without a specific targeted part in metadata
    burning_effect_generic = Effect(
        name=C.EFFECT_BURNING,
        magnitude=1.0,
        ttl=1,
        on_apply="Burning!",
        on_tick="Takes burn damage generally.",
        metadata={},
    )
    fighter.debuffs.append(burning_effect_generic)

    initial_pain = fighter.pain
    initial_heat = fighter.heat
    initial_all_parts_hp = {p_name: sum(l.max_hp for l in p.layers) for p_name, p in fighter.parts.items()}

    fighter.apply_effects()

    assert fighter.pain == initial_pain  # Pain should not change if no specific part is burned
    assert fighter.heat == initial_heat + int(burning_effect_generic.magnitude * 5)

    for p_name, p_hp in initial_all_parts_hp.items():
        assert sum(l.max_hp for l in fighter.parts[p_name].layers) == p_hp, f"Part {p_name} HP changed unexpectedly"

    assert not any(eff.name == C.EFFECT_BURNING for eff in fighter.debuffs)  # Effect expired


def test_apply_effects_bleeding_increases_stats(humanoid_fighter: FighterState):
    fighter = humanoid_fighter
    part_name = "left_arm"
    bleeding_effect = Effect(
        name=C.EFFECT_BLEEDING,
        magnitude=3.0,
        ttl=2,
        on_apply="Arm is bleeding!",
        on_tick="Losing blood from arm.",
        metadata={C.TARGETED_PART: part_name},  # Metadata useful for logging, not direct damage here
    )
    fighter.debuffs.append(bleeding_effect)

    initial_pain = fighter.pain
    initial_exhaustion = fighter.exhaustion

    fighter.apply_effects()  # First tick

    assert fighter.pain == initial_pain + int(bleeding_effect.magnitude * 1)
    assert fighter.exhaustion == initial_exhaustion + int(bleeding_effect.magnitude * 0.5)
    assert any(eff.name == C.EFFECT_BLEEDING for eff in fighter.debuffs)  # Still active
    assert fighter.debuffs[0].ttl == 1  # TTL reduced

    # Second tick
    current_pain = fighter.pain
    current_exhaustion = fighter.exhaustion
    fighter.apply_effects()

    assert fighter.pain == current_pain + int(bleeding_effect.magnitude * 1)
    assert fighter.exhaustion == current_exhaustion + int(bleeding_effect.magnitude * 0.5)
    assert not any(eff.name == C.EFFECT_BLEEDING for eff in fighter.debuffs)  # Expired


def test_apply_delta_removes_effects(humanoid_fighter: FighterState):
    fighter = humanoid_fighter
    effect_to_remove = Effect(name="BadLuck", magnitude=1.0, ttl=5, on_apply="Feeling unlucky")
    fighter.debuffs.append(effect_to_remove)
    assert len(fighter.debuffs) == 1

    delta = {C.EFFECTS_REMOVED: ["BadLuck"]}
    fighter.apply_delta(delta)
    assert len(fighter.debuffs) == 0


def test_apply_delta_effect_removal_is_specific(humanoid_fighter: FighterState):
    fighter = humanoid_fighter
    effect1 = Effect(name="Dizzy", magnitude=1, ttl=3, on_apply="Spinning")
    effect2 = Effect(name="Weakened", magnitude=1, ttl=3, on_apply="Feeble")
    fighter.debuffs.extend([effect1, effect2])
    assert len(fighter.debuffs) == 2

    delta = {C.EFFECTS_REMOVED: ["Dizzy"]}
    fighter.apply_delta(delta)
    assert len(fighter.debuffs) == 1
    assert fighter.debuffs[0].name == "Weakened"


def test_apply_delta_vital_part_destruction_in_wound(humanoid_fighter: FighterState):
    fighter = humanoid_fighter
    part_name = "heart"  # Heart is vital
    assert fighter.parts[part_name].is_vital
    assert fighter.status == C.STATUS_FIGHTING

    heart_hp = sum(layer.max_hp for layer in fighter.parts[part_name].layers)
    delta = {C.WOUNDS: [{C.TARGETED_PART: part_name, C.VALUE: heart_hp + 5, C.TYPE: C.DAMAGE_TYPE_PIERCING}]}
    fighter.apply_delta(delta)
    assert fighter.parts[part_name].status == C.IS_DESTROYED
    assert fighter.status == C.STATUS_UNCONSCIOUS  # Or C.STATUS_DEAD depending on exact logic for single vital part


def test_apply_effects_multiple_effects_simultaneously(humanoid_fighter: FighterState):
    fighter = humanoid_fighter
    torso = "torso"
    leg = "left_leg"
    fighter.parts[leg].bleed_rate = 1

    burning_effect = Effect(
        name=C.EFFECT_BURNING, magnitude=1.0, ttl=1, on_apply="Burning", metadata={C.TARGETED_PART: torso}
    )
    bleeding_effect = Effect(
        name=C.EFFECT_BLEEDING, magnitude=2.0, ttl=1, on_apply="Bleeding", metadata={C.TARGETED_PART: leg}
    )
    fighter.debuffs.extend([burning_effect, bleeding_effect])

    initial_pain = fighter.pain
    initial_heat = fighter.heat
    initial_exhaustion = fighter.exhaustion
    initial_torso_hp = sum(l.max_hp for l in fighter.parts[torso].layers)

    fighter.apply_effects()

    # Burning effects
    expected_burn_damage = max(1, int(burning_effect.magnitude))
    assert fighter.heat == initial_heat + int(burning_effect.magnitude * 5)
    assert sum(l.max_hp for l in fighter.parts[torso].layers) == initial_torso_hp - expected_burn_damage

    # Bleeding effects
    assert fighter.exhaustion == initial_exhaustion + int(bleeding_effect.magnitude * 0.5)

    # Combined pain: from burn damage + from bleeding effect direct
    assert fighter.pain == initial_pain + expected_burn_damage + int(bleeding_effect.magnitude * 1)

    assert not fighter.debuffs  # Both effects had TTL 1


def test_apply_effects_buff_ttl_tick(humanoid_fighter: FighterState):
    fighter = humanoid_fighter
    # Effect type (buff/debuff) is determined by which list it's added to, not a field on Effect itself.
    buff_effect = Effect(name="AgilityBoost", magnitude=1.0, ttl=2, on_apply="Feeling nimble!")  # Removed type=C.BUFFS
    fighter.buffs.append(buff_effect)
    assert len(fighter.buffs) == 1

    fighter.apply_effects()
    assert len(fighter.buffs) == 1
    assert fighter.buffs[0].ttl == 1

    fighter.apply_effects()
    assert len(fighter.buffs) == 0  # Expired


def test_apply_delta_max_pain_induces_death(humanoid_fighter: FighterState):
    fighter = humanoid_fighter
    assert fighter.status == C.STATUS_FIGHTING
    # Delta that doesn't directly change status but increases pain to >= MAX_PAIN_BEFORE_DEATH
    delta = {C.PAIN_INCREASE: C.MAX_PAIN_BEFORE_DEATH}
    fighter.apply_delta(delta)
    assert fighter.pain >= C.MAX_PAIN_BEFORE_DEATH
    assert fighter.status == C.STATUS_DEAD


# All major functionality of state.py seems covered now.
