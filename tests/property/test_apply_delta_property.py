from hypothesis import given, settings, strategies as st

from src.state import FighterState
from src.anatomy import PRESETS
from src.engine import constants as C


@st.composite
def delta_strategy(draw):
    part_names = list(PRESETS["humanoid"].parts.keys())
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
                max_size=3,
            )
        )
        delta[C.WOUNDS] = wounds
    return delta


@given(delta=delta_strategy())
@settings(max_examples=25)
def test_apply_delta_property(delta):
    fighter = FighterState.from_preset("prop_test", "humanoid")
    fighter.apply_delta(delta)

    assert fighter.pain >= 0
    assert fighter.exhaustion >= 0
    assert fighter.heat >= 0
    assert fighter.status in {
        C.STATUS_FIGHTING,
        C.STATUS_UNCONSCIOUS,
        C.STATUS_DEAD,
    }
    for part in fighter.parts.values():
        for layer in part.layers:
            assert layer.max_hp >= 0
