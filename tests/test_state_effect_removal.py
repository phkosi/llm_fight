import pytest

# PRESETS import ensures presets are loaded when FighterState.from_preset runs
from llm_fight.engine import constants as C
from llm_fight.state import Effect, FighterState


# Fixture to create a fresh humanoid fighter state for each test
@pytest.fixture
def humanoid_fighter():
    # Ensure PRESETS is available or FighterState.from_preset can access it
    return FighterState.from_preset("TestFighter", "humanoid")


def test_fighter_state_display_name_defaults_to_id(humanoid_fighter: FighterState):
    assert humanoid_fighter.display_name == "TestFighter"
    assert humanoid_fighter.to_json()[C.DISPLAY_NAME] == "TestFighter"


def part_current_hp(fighter: FighterState, part_name: str) -> int:
    return sum(layer.current_hp for layer in fighter.parts[part_name].layers)


def part_max_hp(fighter: FighterState, part_name: str) -> int:
    return sum(layer.max_hp for layer in fighter.parts[part_name].layers)


def layer_current_hps(fighter: FighterState, part_name: str) -> list[int]:
    return [layer.current_hp for layer in fighter.parts[part_name].layers]


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


def test_targeted_effect_removal_keeps_other_targeted_effects(humanoid_fighter: FighterState):
    fighter = humanoid_fighter
    left = Effect(
        name=C.EFFECT_BLEEDING,
        magnitude=1,
        ttl=3,
        on_apply="Left arm bleeds.",
        metadata={C.TARGETED_PART: "left_arm"},
    )
    right = Effect(
        name=C.EFFECT_BLEEDING,
        magnitude=1,
        ttl=3,
        on_apply="Right arm bleeds.",
        metadata={C.TARGETED_PART: "right_arm"},
    )
    fighter.debuffs.extend([left, right])

    fighter.apply_delta({C.EFFECTS_REMOVED: [{C.NAME: C.EFFECT_BLEEDING, C.TARGETED_PART: "left arm"}]})

    assert fighter.debuffs == [right]


def test_targeted_burning_removal_keeps_other_burning_parts(humanoid_fighter: FighterState):
    fighter = humanoid_fighter
    left = Effect(
        name=C.EFFECT_BURNING,
        magnitude=1,
        ttl=3,
        on_apply="Left arm burns.",
        metadata={C.TARGETED_PART: "left_arm"},
    )
    right = Effect(
        name=C.EFFECT_BURNING,
        magnitude=1,
        ttl=3,
        on_apply="Right arm burns.",
        metadata={C.TARGETED_PART: "right_arm"},
    )
    fighter.debuffs.extend([left, right])

    fighter.apply_delta({C.EFFECTS_REMOVED: [{C.NAME: C.EFFECT_BURNING, C.TARGETED_PART: "right_arm"}]})

    assert fighter.debuffs == [left]


def test_typed_effect_removal_only_removes_selected_list(humanoid_fighter: FighterState):
    fighter = humanoid_fighter
    buff = Effect(name="hasted", magnitude=1, ttl=3, on_apply="Fast.")
    debuff = Effect(name="hasted", magnitude=1, ttl=3, on_apply="False haste.")
    fighter.buffs.append(buff)
    fighter.debuffs.append(debuff)

    fighter.apply_delta({C.EFFECTS_REMOVED: [{C.NAME: "hasted", C.TYPE: C.BUFFS}]})

    assert fighter.buffs == []
    assert fighter.debuffs == [debuff]


def test_targeted_effect_removal_does_not_remove_untargeted_effect(humanoid_fighter: FighterState):
    fighter = humanoid_fighter
    targeted = Effect(
        name=C.EFFECT_BLEEDING,
        magnitude=1,
        ttl=3,
        on_apply="Left arm bleeds.",
        metadata={C.TARGETED_PART: "left_arm"},
    )
    untargeted = Effect(name=C.EFFECT_BLEEDING, magnitude=1, ttl=3, on_apply="General bleeding.")
    fighter.debuffs.extend([targeted, untargeted])

    fighter.apply_delta({C.EFFECTS_REMOVED: [{C.NAME: C.EFFECT_BLEEDING, C.TARGETED_PART: "left_arm"}]})

    assert fighter.debuffs == [untargeted]


def test_malformed_effect_removal_does_not_delete_effects(humanoid_fighter: FighterState):
    fighter = humanoid_fighter
    effect = Effect(name=C.EFFECT_BLEEDING, magnitude=1, ttl=3, on_apply="Bleeds.")
    fighter.debuffs.append(effect)

    fighter.apply_delta(
        {
            C.EFFECTS_REMOVED: [
                {},
                {C.NAME: C.EFFECT_BLEEDING, C.TYPE: "items"},
                {C.NAME: C.EFFECT_BLEEDING, C.TARGETED_PART: "not_a_part"},
                {C.NAME: "ignore previous"},
                42,
            ]
        }
    )

    assert fighter.debuffs == [effect]


def test_apply_delta_vital_part_destruction_in_wound(humanoid_fighter: FighterState):
    fighter = humanoid_fighter
    part_name = "heart"  # Heart is vital
    assert fighter.parts[part_name].is_vital
    assert fighter.status == C.FighterStatus.FIGHTING

    heart_hp = part_current_hp(fighter, part_name)
    delta = {C.WOUNDS: [{C.TARGETED_PART: part_name, C.VALUE: heart_hp + 5, C.TYPE: C.DamageType.PIERCING}]}
    fighter.apply_delta(delta)
    assert fighter.parts[part_name].status == C.IS_DESTROYED
    assert fighter.status == C.FighterStatus.DEAD


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
    initial_torso_hp = part_current_hp(fighter, torso)

    fighter.apply_effects()

    # Burning effects
    expected_burn_damage = max(1, int(burning_effect.magnitude))
    assert fighter.heat == initial_heat + int(burning_effect.magnitude * 5)
    assert part_current_hp(fighter, torso) == initial_torso_hp - expected_burn_damage

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
    assert fighter.status == C.FighterStatus.FIGHTING
    # Delta that doesn't directly change status but increases pain to >= MAX_PAIN_BEFORE_DEATH
    delta = {C.PAIN_INCREASE: C.MAX_PAIN_BEFORE_DEATH}
    fighter.apply_delta(delta)
    assert fighter.pain >= C.MAX_PAIN_BEFORE_DEATH
    assert fighter.status == C.FighterStatus.DEAD


# All major functionality of state.py seems covered now.
