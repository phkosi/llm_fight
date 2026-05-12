from hypothesis import given, settings, strategies as st

from llm_fight.state import Effect, FighterState
from llm_fight.anatomy import PRESETS
from llm_fight.engine import constants as C


@st.composite
def delta_strategy(draw):
    """Generate a random delta covering wounds and effect operations."""
    part_names = list(PRESETS["humanoid"].parts.keys())
    effect_names = ["BuffA", "DebuffB", "DupEffect", "Seeded"]

    delta = {}

    if draw(st.booleans()):
        delta[C.PAIN_INCREASE] = draw(st.integers(min_value=0, max_value=150))
    if draw(st.booleans()):
        delta[C.EXHAUSTION_INCREASE] = draw(st.integers(min_value=0, max_value=150))
    if draw(st.booleans()):
        delta[C.HEAT_INCREASE] = draw(st.integers(min_value=0, max_value=150))

    if draw(st.booleans()):
        wounds = draw(
            st.lists(
                st.fixed_dictionaries(
                    {
                        C.TARGETED_PART: st.sampled_from(part_names),
                        C.VALUE: st.integers(min_value=1, max_value=20),
                        C.TYPE: st.sampled_from(
                            [
                                C.DamageType.PIERCING,
                                C.DamageType.SLASHING,
                                C.DamageType.FIRE,
                            ]
                        ),
                    }
                ),
                min_size=1,
                max_size=5,
            )
        )
        delta[C.WOUNDS] = wounds

    if draw(st.booleans()):
        effects_added = draw(
            st.lists(
                st.fixed_dictionaries(
                    {
                        C.NAME: st.sampled_from(effect_names),
                        C.VALUE: st.floats(min_value=0.5, max_value=3.0),
                        C.EFFECT_TTL: st.integers(min_value=-1, max_value=3),
                        C.TYPE: st.sampled_from([C.BUFFS, C.DEBUFFS]),
                    }
                ),
                min_size=1,
                max_size=3,
            )
        )
        delta[C.EFFECTS_ADDED] = effects_added

    if draw(st.booleans()):
        removals = draw(
            st.lists(
                st.one_of(
                    st.sampled_from(effect_names),
                    st.fixed_dictionaries(
                        {
                            C.NAME: st.sampled_from(effect_names),
                            C.TYPE: st.sampled_from([C.BUFFS, C.DEBUFFS]),
                        }
                    ),
                    st.fixed_dictionaries(
                        {
                            C.NAME: st.sampled_from(effect_names),
                            C.TARGETED_PART: st.sampled_from(part_names),
                        }
                    ),
                    st.fixed_dictionaries(
                        {
                            C.NAME: st.sampled_from(effect_names),
                            C.TYPE: st.sampled_from([C.BUFFS, C.DEBUFFS]),
                            C.TARGETED_PART: st.sampled_from(part_names),
                        }
                    ),
                ),
                min_size=1,
                max_size=3,
            )
        )
        delta[C.EFFECTS_REMOVED] = removals

    return delta


@given(delta=delta_strategy())
@settings(max_examples=50)
def test_apply_delta_property(delta):
    fighter = FighterState.from_preset("prop_test", "humanoid")
    seeded_left = Effect(
        name="Seeded",
        magnitude=1,
        ttl=3,
        on_apply="Left seeded effect.",
        metadata={C.TARGETED_PART: "left_arm"},
    )
    seeded_right = Effect(
        name="Seeded",
        magnitude=1,
        ttl=3,
        on_apply="Right seeded effect.",
        metadata={C.TARGETED_PART: "right_arm"},
    )
    seeded_buff = Effect(name="Seeded", magnitude=1, ttl=3, on_apply="Seeded buff.")
    fighter.debuffs.extend([seeded_left, seeded_right])
    fighter.buffs.append(seeded_buff)

    # Snapshot HP before applying delta
    hp_before = {name: [layer.current_hp for layer in part.layers] for name, part in fighter.parts.items()}
    max_hp_before = {name: [layer.max_hp for layer in part.layers] for name, part in fighter.parts.items()}

    fighter.apply_delta(delta)

    # Stats should remain non-negative
    assert fighter.pain >= 0
    assert fighter.exhaustion >= 0
    assert fighter.heat >= 0

    # Fighter status must be valid
    assert fighter.status in {
        C.FighterStatus.FIGHTING,
        C.FighterStatus.UNCONSCIOUS,
        C.FighterStatus.DEAD,
    }

    # No body part current HP should increase from applying the delta, and max HP should stay stable.
    for name, part in fighter.parts.items():
        for idx, layer in enumerate(part.layers):
            assert layer.current_hp <= hp_before[name][idx]
            assert layer.max_hp == max_hp_before[name][idx]

    # Adding duplicate permanent effects should not create multiple entries
    permanent_names = [eff.name for eff in (fighter.buffs + fighter.debuffs) if eff.ttl == -1]
    assert len(permanent_names) == len(set(permanent_names))

    removal_selectors = delta.get(C.EFFECTS_REMOVED, [])
    targeted_seeded_removal = any(
        isinstance(selector, dict)
        and selector.get(C.NAME) == "Seeded"
        and selector.get(C.TARGETED_PART) in {"left_arm", "left arm", "left-arm"}
        and selector.get(C.TYPE) in {None, C.DEBUFFS}
        for selector in removal_selectors
    )
    right_targeted_seeded_removal = any(
        isinstance(selector, dict)
        and selector.get(C.NAME) == "Seeded"
        and selector.get(C.TARGETED_PART) in {"right_arm", "right arm", "right-arm"}
        and selector.get(C.TYPE) in {None, C.DEBUFFS}
        for selector in removal_selectors
    )
    broad_seeded_removal = any(
        selector == "Seeded"
        or (
            isinstance(selector, dict)
            and selector.get(C.NAME) == "Seeded"
            and selector.get(C.TARGETED_PART) in (None, "")
            and selector.get(C.TYPE) in {None, C.DEBUFFS}
        )
        for selector in removal_selectors
    )
    right_seeded_exists = any(
        eff.name == "Seeded" and eff.metadata.get(C.TARGETED_PART) == "right_arm" for eff in fighter.debuffs
    )
    if targeted_seeded_removal and not broad_seeded_removal and not right_targeted_seeded_removal:
        assert right_seeded_exists

    # Tick effects and ensure expired ones are removed
    fighter.apply_effects()
    assert not any(eff.ttl == 0 for eff in fighter.buffs + fighter.debuffs)

    for part in fighter.parts.values():
        for layer in part.layers:
            assert layer.current_hp >= 0
            assert layer.max_hp >= layer.current_hp
