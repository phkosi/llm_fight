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
    initial_part_hp = part_current_hp(fighter, part_name)

    fighter.apply_effects()

    expected_burn_damage = max(1, int(burning_effect.magnitude))
    assert fighter.pain == initial_pain + expected_burn_damage  # Corrected expected pain
    assert fighter.heat == initial_heat + int(burning_effect.magnitude * 5)

    final_part_hp = part_current_hp(fighter, part_name)
    assert final_part_hp == initial_part_hp - expected_burn_damage

    assert not any(eff.name == C.EFFECT_BURNING for eff in fighter.debuffs)


def test_burn_tick_uses_burn_rate_for_damage(humanoid_fighter: FighterState):
    normal = FighterState.from_preset("normal", "humanoid")
    hot = FighterState.from_preset("hot", "humanoid")
    part_name = "torso"
    hot.parts[part_name].burn_rate = 3
    for fighter in (normal, hot):
        fighter.debuffs.append(
            Effect(
                name=C.EFFECT_BURNING,
                magnitude=2.0,
                ttl=1,
                on_apply="Torso burns.",
                metadata={C.TARGETED_PART: part_name},
            )
        )
    normal_start = part_current_hp(normal, part_name)
    hot_start = part_current_hp(hot, part_name)

    class FakeRng:
        def choice(self, seq):
            return seq[0]

    normal.apply_effects(rng=FakeRng())
    hot.apply_effects(rng=FakeRng())

    assert normal_start - part_current_hp(normal, part_name) == 2
    assert hot_start - part_current_hp(hot, part_name) == 6


def test_burn_rate_zero_preserves_baseline_burn_damage(humanoid_fighter: FighterState):
    fighter = humanoid_fighter
    part_name = "left_arm"
    fighter.parts[part_name].burn_rate = 0
    fighter.debuffs.append(
        Effect(
            name=C.EFFECT_BURNING,
            magnitude=2.0,
            ttl=1,
            on_apply="Arm burns.",
            metadata={C.TARGETED_PART: part_name},
        )
    )
    start_hp = part_current_hp(fighter, part_name)

    fighter.apply_effects()

    assert start_hp - part_current_hp(fighter, part_name) == 2


def test_burn_tick_mutates_selected_layer_and_logs_it(humanoid_fighter: FighterState, caplog):
    fighter = humanoid_fighter
    part_name = "torso"
    target_part = fighter.parts[part_name]
    fighter.debuffs.append(
        Effect(
            name=C.EFFECT_BURNING,
            magnitude=3.0,
            ttl=1,
            on_apply="Torso burns.",
            metadata={C.TARGETED_PART: part_name},
        )
    )

    class FakeRng:
        def choice(self, seq):
            return seq[-1]

    before_current = [layer.current_hp for layer in target_part.layers]
    before_max = [layer.max_hp for layer in target_part.layers]

    with caplog.at_level("DEBUG", logger="llm_fight_engine"):
        fighter.apply_effects(rng=FakeRng())

    after_current = [layer.current_hp for layer in target_part.layers]
    after_max = [layer.max_hp for layer in target_part.layers]
    changed = [
        idx for idx, (before, after) in enumerate(zip(before_current, after_current, strict=False)) if before != after
    ]
    assert changed == [len(target_part.layers) - 1]
    assert after_current[-1] == before_current[-1] - 3
    assert after_max == before_max
    assert f"{part_name}.{target_part.layers[-1].name}" in caplog.text
    assert f"HP {after_current[-1]}/{after_max[-1]}" in caplog.text


def test_dynamic_stat_tick_effect_observes_fresh_turn_and_expires(humanoid_fighter: FighterState):
    fighter = humanoid_fighter
    fighter.apply_delta(
        {
            C.EFFECTS_ADDED: [
                {
                    C.NAME: "poisoned",
                    C.VALUE: 2,
                    C.EFFECT_TTL: 1,
                    C.EFFECT_ON_APPLY: "Poison takes hold",
                    C.EFFECT_ON_TICK: "Poison weakens the body",
                    C.EFFECT_MECHANICS: [
                        {
                            C.EFFECT_MECHANIC_KIND: C.EFFECT_MECHANIC_STAT_TICK,
                            C.EFFECT_MECHANIC_STAT: C.PAIN,
                            C.VALUE: 4,
                        },
                        {
                            C.EFFECT_MECHANIC_KIND: C.EFFECT_MECHANIC_STAT_TICK,
                            C.EFFECT_MECHANIC_STAT: C.EXHAUSTION,
                            C.VALUE: 2,
                        },
                    ],
                    C.EFFECT_TAGS: ["poison"],
                }
            ]
        }
    )

    fighter.apply_effects()
    assert fighter.pain == 0
    assert fighter.exhaustion == 0
    assert fighter.debuffs[0].fresh_turns == 0

    fighter.apply_effects()
    assert fighter.pain == 4
    assert fighter.exhaustion == 2
    assert fighter.debuffs == []


def test_dynamic_damage_tick_effect_targets_valid_custom_part(humanoid_fighter: FighterState):
    fighter = humanoid_fighter
    initial_hp = part_current_hp(fighter, "torso")
    fighter.debuffs.append(
        Effect(
            name="corroded",
            magnitude=1,
            ttl=1,
            on_apply="Acid clings to the torso",
            mechanics=[
                {
                    C.EFFECT_MECHANIC_KIND: C.EFFECT_MECHANIC_DAMAGE_TICK,
                    C.TARGETED_PART: "torso",
                    C.VALUE: 3,
                    C.TYPE: C.DamageType.GENERIC.value,
                }
            ],
        )
    )

    fighter.apply_effects()

    assert part_current_hp(fighter, "torso") == initial_hp - 3
    assert fighter.debuffs == []


def test_invalid_dynamic_mechanic_rejected_before_state(humanoid_fighter: FighterState):
    fighter = humanoid_fighter
    fighter.apply_delta(
        {
            C.EFFECTS_ADDED: [
                {
                    C.NAME: "corroded",
                    C.VALUE: 1,
                    C.EFFECT_TTL: 2,
                    C.EFFECT_ON_APPLY: "Acid starts working",
                    C.EFFECT_MECHANICS: [
                        {
                            C.EFFECT_MECHANIC_KIND: C.EFFECT_MECHANIC_DAMAGE_TICK,
                            C.TARGETED_PART: "not_a_part",
                            C.VALUE: 2,
                        }
                    ],
                }
            ]
        }
    )

    assert fighter.debuffs == []


def test_dynamic_effect_serializes_mechanics_and_tags(humanoid_fighter: FighterState):
    fighter = humanoid_fighter
    fighter.debuffs.append(
        Effect(
            name="blinded",
            magnitude=1,
            ttl=2,
            on_apply="Eyes are obscured",
            mechanics=[
                {
                    C.EFFECT_MECHANIC_KIND: C.EFFECT_MECHANIC_TARGETING_MODIFIER,
                    C.EFFECT_MECHANIC_MODIFIER: C.EFFECT_MECHANIC_OUTGOING_ACCURACY_PENALTY,
                    C.VALUE: 40,
                }
            ],
            tags=["vision_impaired"],
        )
    )

    serialized = fighter.to_json()[C.DEBUFFS][0]

    assert serialized[C.EFFECT_MECHANICS][0][C.VALUE] == 40
    assert serialized[C.EFFECT_TAGS] == ["vision_impaired"]


def test_apply_effects_uses_provided_rng_for_burn_layer_selection(humanoid_fighter: FighterState):
    fighter = humanoid_fighter
    part_name = "torso"
    fighter.debuffs.append(
        Effect(
            name=C.EFFECT_BURNING,
            magnitude=1.0,
            ttl=1,
            on_apply="Torso is burning!",
            metadata={C.TARGETED_PART: part_name},
        )
    )

    class FakeRng:
        def __init__(self):
            self.choice_calls = 0

        def choice(self, seq):
            self.choice_calls += 1
            return seq[-1]

    fake_rng = FakeRng()

    fighter.apply_effects(rng=fake_rng)

    assert fake_rng.choice_calls == 1


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
    initial_all_parts_hp = {p_name: part_current_hp(fighter, p_name) for p_name in fighter.parts}

    fighter.apply_effects()

    assert fighter.pain == initial_pain  # Pain should not change if no specific part is burned
    assert fighter.heat == initial_heat + int(burning_effect_generic.magnitude * 5)

    for p_name, p_hp in initial_all_parts_hp.items():
        assert part_current_hp(fighter, p_name) == p_hp, f"Part {p_name} HP changed unexpectedly"

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


def test_apply_effects_can_trigger_death_from_status_invariants(humanoid_fighter: FighterState):
    fighter = humanoid_fighter
    fighter.debuffs.append(
        Effect(
            name=C.EFFECT_BLEEDING,
            magnitude=float(C.MAX_PAIN_BEFORE_DEATH),
            ttl=1,
            on_apply="Massive bleeding",
            metadata={C.TARGETED_PART: "torso"},
        )
    )

    fighter.apply_effects()

    assert fighter.status == C.FighterStatus.DEAD
