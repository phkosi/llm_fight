from hypothesis import given, settings, strategies as st

from llm_fight.state import FighterState
from llm_fight.anatomy import PRESETS
from llm_fight.engine import constants as C


@st.composite
def damage_sequence(draw):
    """Generate a list of random damage operations."""
    part_names = list(PRESETS["humanoid"].parts.keys())
    damage_types = [
        C.DAMAGE_TYPE_PIERCING,
        C.DAMAGE_TYPE_SLASHING,
        C.DAMAGE_TYPE_FIRE,
        C.DAMAGE_TYPE_GENERIC,
    ]

    return draw(
        st.lists(
            st.fixed_dictionaries(
                {
                    C.TARGETED_PART: st.sampled_from(part_names),
                    C.VALUE: st.integers(min_value=1, max_value=30),
                    C.TYPE: st.sampled_from(damage_types),
                }
            ),
            min_size=1,
            max_size=10,
        )
    )


@given(ops=damage_sequence())
@settings(max_examples=50)
def test_apply_damage_property(ops):
    fighter = FighterState.from_preset("prop_damage", "humanoid")

    for op in ops:
        part_name = op[C.TARGETED_PART]
        dmg = op[C.VALUE]
        dmg_type = op[C.TYPE]

        part = fighter.parts[part_name]
        hp_before = [layer.max_hp for layer in part.layers]
        severed_before = part.severed

        fighter.apply_damage_to_part(part_name, dmg, dmg_type)

        hp_after = [layer.max_hp for layer in part.layers]

        # HP should never increase
        for before, after in zip(hp_before, hp_after):
            assert after <= before

        # Severed parts take no further HP damage
        if severed_before:
            assert hp_after == hp_before

        if all(layer_hp <= 0 for layer_hp in hp_after):
            if part.can_be_severed:
                assert part.severed
                assert part.status == C.STATUS_SEVERED
            else:
                assert part.status == C.IS_DESTROYED

            if part.is_vital:
                assert fighter.status in {C.STATUS_UNCONSCIOUS, C.STATUS_DEAD}

        assert fighter.status in {
            C.STATUS_FIGHTING,
            C.STATUS_UNCONSCIOUS,
            C.STATUS_DEAD,
        }
