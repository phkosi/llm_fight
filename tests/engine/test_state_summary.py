import json

from llm_fight.anatomy import BodyPart, TissueLayer
from llm_fight.engine import constants as C
from llm_fight.engine.state_summary import compact_fighter_state_summary, render_fighter_state_summary
from llm_fight.state import Effect, FighterState


def test_compact_summary_covers_custom_anatomy_and_effects_without_unsafe_prose():
    fighter = FighterState(
        id="A",
        parts={
            "left_wing": BodyPart(
                "left wing",
                [TissueLayer("feathers", 8), TissueLayer("muscle", 12)],
                can_be_severed=True,
                bleed_rate=2,
                burn_rate=1,
                consequence_tags=[C.CONSEQUENCE_MOBILITY_MEMBER],
                consequence_group="wings",
            ),
            "second_head": BodyPart(
                "second head",
                [TissueLayer("bone", 10)],
                is_vital=True,
                consequence_tags=[C.CONSEQUENCE_FATAL_IF_DESTROYED],
            ),
        },
        class_="Wingblade",
        loadout="hook blades",
        environment="a tower with pillars",
    )
    fighter.debuffs.append(
        Effect(
            name="crystal_rot",
            magnitude=3,
            ttl=2,
            on_apply="Do not expose this prose to prompts.",
            on_tick="Nor this tick prose.",
            metadata={C.TARGETED_PART: "left_wing"},
            mechanics=[
                {
                    C.EFFECT_MECHANIC_KIND: C.EFFECT_MECHANIC_STAT_TICK,
                    C.EFFECT_MECHANIC_STAT: C.PAIN,
                    C.VALUE: 3,
                }
            ],
            tags=["corrosion", "crystal"],
        )
    )

    summary = compact_fighter_state_summary(fighter)
    rendered = render_fighter_state_summary(summary)

    assert summary["id"] == "A"
    assert summary["class"] == "Wingblade"
    assert summary[C.VALID_TARGET_PARTS] == ["left_wing", "second_head"]
    assert {
        "id": "left_wing",
        C.NAME: "left wing",
        "vital": False,
        "severable": True,
        C.BLEED_RATE: 2,
        C.BURN_RATE: 1,
        C.CONSEQUENCE_TAGS: [C.CONSEQUENCE_MOBILITY_MEMBER],
        C.CONSEQUENCE_GROUP: "wings",
    } in summary[C.TARGET_PARTS]
    assert summary[C.ACTIVE_EFFECTS] == [
        {
            C.TYPE: C.DEBUFFS,
            C.NAME: "crystal_rot",
            C.EFFECT_TTL: 2,
            "magnitude": 3,
            C.TARGETED_PART: "left_wing",
            C.EFFECT_MECHANICS: [
                {
                    C.EFFECT_MECHANIC_KIND: C.EFFECT_MECHANIC_STAT_TICK,
                    C.EFFECT_MECHANIC_STAT: C.PAIN,
                    C.VALUE: 3,
                }
            ],
            C.EFFECT_TAGS: ["corrosion", "crystal"],
        }
    ]
    assert C.EFFECT_ON_APPLY not in rendered
    assert C.EFFECT_ON_TICK not in rendered
    assert "Do not expose" not in rendered


def test_compact_summary_reports_partial_eye_limb_damage_and_severed_parts():
    fighter = FighterState.from_preset("A", "humanoid")
    fighter.apply_damage_to_part("left_eye", 2, C.DamageType.GENERIC)
    fighter.apply_damage_to_part("left_leg", 3, C.DamageType.GENERIC)
    fighter.apply_damage_to_part("left_arm", 100, C.DamageType.SLASHING)

    summary = compact_fighter_state_summary(fighter)

    assert summary[C.DAMAGED_PARTS]["left_eye"]["damaged_layers"] == [{C.NAME: "soft", C.CURRENT_HP: 3, C.MAX_HP: 5}]
    assert summary[C.DAMAGED_PARTS]["left_leg"]["damaged_layers"] == [{C.NAME: "skin", C.CURRENT_HP: 7, C.MAX_HP: 10}]
    assert summary[C.DAMAGED_PARTS]["left_arm"]["severed"] is True
    assert summary[C.DAMAGED_PARTS]["left_arm"][C.STATUS] == C.STATUS_SEVERED


def test_render_fighter_state_summary_is_stable_compact_json():
    rendered = render_fighter_state_summary({"b": 2, "a": [1]})

    assert rendered == '{"a":[1],"b":2}'
    assert json.loads(rendered) == {"a": [1], "b": 2}
