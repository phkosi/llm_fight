from hypothesis import given, settings, strategies as st

from src.state import FighterState
from src.anatomy import PRESETS
from src.engine import constants as C


@st.composite
def delta_strategy(draw):
    """Generate a random delta covering wounds and effect operations."""
    part_names = list(PRESETS["humanoid"].parts.keys())
    effect_names = ["BuffA", "DebuffB", "DupEffect"]

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
                        C.TYPE: st.sampled_from([
                            C.DAMAGE_TYPE_PIERCING,
                            C.DAMAGE_TYPE_SLASHING,
                            C.DAMAGE_TYPE_FIRE,
                        ]),
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
        remove_names = draw(
            st.lists(
                st.sampled_from(effect_names),
                min_size=1,
                max_size=3,
            )
        )
        delta[C.EFFECTS_REMOVED] = remove_names

    return delta


@given(delta=delta_strategy())
@settings(max_examples=50)
def test_apply_delta_property(delta):
    fighter = FighterState.from_preset("prop_test", "humanoid")

    # Snapshot HP before applying delta
    hp_before = {
        name: [layer.max_hp for layer in part.layers]
        for name, part in fighter.parts.items()
    }

    fighter.apply_delta(delta)

    # Stats should remain non-negative
    assert fighter.pain >= 0
    assert fighter.exhaustion >= 0
    assert fighter.heat >= 0

    # Fighter status must be valid
    assert fighter.status in {
        C.STATUS_FIGHTING,
        C.STATUS_UNCONSCIOUS,
        C.STATUS_DEAD,
    }

    # No body part HP should increase from applying the delta
    for name, part in fighter.parts.items():
        for idx, layer in enumerate(part.layers):
            assert layer.max_hp <= hp_before[name][idx]

    # Adding duplicate permanent effects should not create multiple entries
    permanent_names = [
        eff.name for eff in (fighter.buffs + fighter.debuffs) if eff.ttl == -1
    ]
    assert len(permanent_names) == len(set(permanent_names))

    # Tick effects and ensure expired ones are removed
    fighter.apply_effects()
    assert not any(eff.ttl == 0 for eff in fighter.buffs + fighter.debuffs)

    for part in fighter.parts.values():
        for layer in part.layers:
            assert layer.max_hp >= 0
