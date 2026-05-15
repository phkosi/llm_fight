import llm_fight.simulation as sim_module
from llm_fight.engine import constants as C
from llm_fight.profiles import build_fighter_profile
from llm_fight.state import FighterState


def _custom_profile(part_id: str, vital: bool = True):
    return {
        C.CONFIG_FIGHTER_CLASS: f"{part_id} fighter",
        C.LOADOUT: "profile weapon",
        "environment": "profile arena",
        C.BODY_PARTS: [
            {
                "id": part_id,
                "is_vital": vital,
                "layers": [{C.NAME: "core", C.MAX_HP: 12}],
            },
            {
                "id": f"{part_id}_limb",
                "can_be_severed": True,
                "layers": [{C.NAME: "muscle", C.MAX_HP: 8}],
            },
        ],
    }


def test_phase2_canonicalizes_wound_to_unique_target_owned_narration_part():
    fighters = {
        C.FIGHTER_A: FighterState.from_preset(C.FIGHTER_A, "humanoid"),
        C.FIGHTER_B: FighterState.from_preset(C.FIGHTER_B, "humanoid"),
    }
    fighters[C.FIGHTER_A].display_name = "Sir Galant"
    fighters[C.FIGHTER_B].display_name = "Shade"
    p1 = {
        f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": False,
        f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
    }
    rolls = {C.FIGHTER_A: False, C.FIGHTER_B: True}
    p2 = {
        C.NARRATION: "Shade strikes Sir Galant's left arm with the poison dagger.",
        C.DELTA: {
            C.FIGHTER_A: {
                C.WOUNDS: [
                    {
                        C.SOURCE: C.FIGHTER_B,
                        C.TARGETED_PART: "right_arm",
                        C.VALUE: 10,
                        C.TYPE: C.DamageType.PIERCING,
                    }
                ]
            }
        },
        C.FIGHT_END: False,
        C.WINNER: None,
    }

    sanitized = sim_module._authorize_phase2_result(
        p2,
        p1,
        rolls,
        fighters,
        attempts={
            C.FIGHTER_A: "I hold my ground.",
            C.FIGHTER_B: "I strike Sir Galant with my poison dagger.",
        },
    )

    wound = sanitized[C.DELTA][C.FIGHTER_A][C.WOUNDS][0]
    assert wound[C.TARGETED_PART] == "left_arm"
    assert sanitized[C.VALIDATION_WARNINGS][0]["reason"] == "narration_named_different_target"


def test_phase2_repair_does_not_invent_damage_from_self_care_body_part_text():
    fighters = {
        C.FIGHTER_A: FighterState.from_preset(C.FIGHTER_A, "humanoid"),
        C.FIGHTER_B: FighterState.from_preset(C.FIGHTER_B, "humanoid"),
    }
    p1 = {
        f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
        f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
    }
    rolls = {C.FIGHTER_A: True, C.FIGHTER_B: True}
    p2 = {
        C.NARRATION: "Both fighters reposition.",
        C.DELTA: {},
        C.FIGHT_END: False,
        C.WINNER: None,
    }

    sanitized = sim_module._authorize_phase2_result(
        p2,
        p1,
        rolls,
        fighters,
        attempts={
            C.FIGHTER_A: "I adopt a defensive stance behind my shield and stabilize my wounded left arm.",
            C.FIGHTER_B: "I throw a smoke bomb toward Sir Galant's shield.",
        },
    )

    assert set(sanitized[C.DELTA]) == {C.FIGHTER_A}
    effect_names = [effect[C.NAME] for effect in sanitized[C.DELTA][C.FIGHTER_A][C.EFFECTS_ADDED]]
    assert effect_names == ["guarded", "obscured"]
    assert C.WOUNDS not in sanitized[C.DELTA][C.FIGHTER_A]
    assert C.P2_ENGINE_REPAIR_USED in sanitized[C.METADATA]


def test_phase2_repairs_successful_smoke_setup_with_obscured_effect():
    fighters = {
        C.FIGHTER_A: FighterState.from_preset(C.FIGHTER_A, "humanoid"),
        C.FIGHTER_B: FighterState.from_preset(C.FIGHTER_B, "humanoid"),
    }
    fighters[C.FIGHTER_A].display_name = "Sir Galant"
    fighters[C.FIGHTER_B].display_name = "Shade"
    p1 = {
        f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
        f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
    }
    rolls = {C.FIGHTER_A: False, C.FIGHTER_B: True}
    p2 = {
        C.NARRATION: "The exchange is inconclusive.",
        C.DELTA: {},
        C.FIGHT_END: False,
        C.WINNER: None,
    }

    sanitized = sim_module._authorize_phase2_result(
        p2,
        p1,
        rolls,
        fighters,
        attempts={
            C.FIGHTER_A: "I miss with my longsword.",
            C.FIGHTER_B: "I throw a smoke bomb at Sir Galant's face to disorient him.",
        },
    )

    effects = sanitized[C.DELTA][C.FIGHTER_A][C.EFFECTS_ADDED]
    assert effects[0][C.NAME] == "obscured"
    assert effects[0][C.METADATA][C.TARGETED_PART] == "head"
    assert sanitized[C.METADATA][C.P2_ENGINE_REPAIR_USED] is True
    assert "Shade's successful setup leaves Sir Galant obscured" in sanitized[C.NARRATION]


def test_phase2_repair_combines_attack_wound_and_smoke_setup():
    fighters = {
        C.FIGHTER_A: FighterState.from_preset(C.FIGHTER_A, "humanoid"),
        C.FIGHTER_B: FighterState.from_preset(C.FIGHTER_B, "humanoid"),
    }
    fighters[C.FIGHTER_A].display_name = "Sir Galant"
    fighters[C.FIGHTER_B].display_name = "Shade"
    p1 = {
        f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
        f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
    }
    rolls = {C.FIGHTER_A: True, C.FIGHTER_B: True}
    p2 = {
        C.NARRATION: "The exchange is inconclusive.",
        C.DELTA: {},
        C.FIGHT_END: False,
        C.WINNER: None,
    }

    sanitized = sim_module._authorize_phase2_result(
        p2,
        p1,
        rolls,
        fighters,
        attempts={
            C.FIGHTER_A: "I slash Shade's left arm with my longsword.",
            C.FIGHTER_B: "I throw a smoke bomb at Sir Galant's face.",
        },
    )

    assert sanitized[C.DELTA][C.FIGHTER_B][C.WOUNDS][0][C.TARGETED_PART] == "left_arm"
    assert sanitized[C.DELTA][C.FIGHTER_A][C.EFFECTS_ADDED][0][C.NAME] == "obscured"
    assert "Sir Galant's successful attack lands on Shade's left arm" in sanitized[C.NARRATION]
    assert "Shade's successful setup leaves Sir Galant obscured" in sanitized[C.NARRATION]


def test_phase2_smoke_repair_ignores_weapon_target_part():
    fighters = {
        C.FIGHTER_A: FighterState.from_preset(C.FIGHTER_A, "humanoid"),
        C.FIGHTER_B: FighterState.from_preset(C.FIGHTER_B, "humanoid"),
    }
    p1 = {
        f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": False,
        f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
    }
    rolls = {C.FIGHTER_A: False, C.FIGHTER_B: True}
    p2 = {
        C.NARRATION: "Shade lands a precise stab through the smoke.",
        C.DELTA: {},
        C.FIGHT_END: False,
        C.WINNER: None,
    }

    sanitized = sim_module._authorize_phase2_result(
        p2,
        p1,
        rolls,
        fighters,
        attempts={
            C.FIGHTER_A: "I step back.",
            C.FIGHTER_B: "I throw smoke and stab Sir Galant's heart with my poison dagger.",
        },
    )

    obscured = sanitized[C.DELTA][C.FIGHTER_A][C.EFFECTS_ADDED][0]
    assert obscured[C.NAME] == "obscured"
    assert C.METADATA not in obscured


def test_phase2_drops_effect_with_zero_value_mechanic():
    fighters = {
        C.FIGHTER_A: FighterState.from_preset(C.FIGHTER_A, "humanoid"),
        C.FIGHTER_B: FighterState.from_preset(C.FIGHTER_B, "humanoid"),
    }
    p1 = {f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True, f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": False}
    rolls = {C.FIGHTER_A: True, C.FIGHTER_B: False}
    p2 = {
        C.NARRATION: "A creates useless poison.",
        C.DELTA: {
            C.FIGHTER_B: {
                C.EFFECTS_ADDED: [
                    {
                        C.SOURCE: C.FIGHTER_A,
                        C.NAME: "poisoned",
                        C.VALUE: 1,
                        C.EFFECT_TTL: 3,
                        C.EFFECT_ON_APPLY: "Poison takes hold.",
                        C.EFFECT_MECHANICS: [
                            {
                                C.EFFECT_MECHANIC_KIND: C.EFFECT_MECHANIC_STAT_TICK,
                                C.EFFECT_MECHANIC_STAT: C.PAIN,
                                C.VALUE: 0,
                            }
                        ],
                    }
                ]
            }
        },
        C.FIGHT_END: False,
        C.WINNER: None,
    }

    sanitized = sim_module._authorize_phase2_result(
        p2,
        p1,
        rolls,
        fighters,
        attempts={C.FIGHTER_A: "I poison my opponent.", C.FIGHTER_B: "I wait."},
    )

    assert sanitized[C.DELTA] == {}
    assert sanitized[C.VALIDATION_WARNINGS][0]["code"] == C.WARNING_CODE_INVALID_EFFECT_PAYLOAD
    assert sanitized[C.VALIDATION_WARNINGS][0]["reason"] == "invalid_or_noop_mechanics"


def test_phase2_drops_effect_with_object_ttl_or_missing_magnitude():
    fighters = {
        C.FIGHTER_A: FighterState.from_preset(C.FIGHTER_A, "humanoid"),
        C.FIGHTER_B: FighterState.from_preset(C.FIGHTER_B, "humanoid"),
    }
    p1 = {f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True, f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": False}
    rolls = {C.FIGHTER_A: True, C.FIGHTER_B: False}
    p2 = {
        C.NARRATION: "A applies malformed effects.",
        C.DELTA: {
            C.FIGHTER_B: {
                C.EFFECTS_ADDED: [
                    {
                        C.SOURCE: C.FIGHTER_A,
                        C.NAME: "bad_ttl",
                        C.VALUE: 1,
                        C.EFFECT_TTL: {"turns": 3},
                        C.EFFECT_ON_APPLY: "Bad ttl lands.",
                    },
                    {
                        C.SOURCE: C.FIGHTER_A,
                        C.NAME: "missing_value",
                        C.EFFECT_TTL: 3,
                        C.EFFECT_ON_APPLY: "No value lands.",
                    },
                ]
            }
        },
        C.FIGHT_END: False,
        C.WINNER: None,
    }

    sanitized = sim_module._authorize_phase2_result(
        p2,
        p1,
        rolls,
        fighters,
        attempts={C.FIGHTER_A: "I poison my opponent.", C.FIGHTER_B: "I wait."},
    )

    assert sanitized[C.DELTA] == {}
    reasons = [warning["reason"] for warning in sanitized[C.VALIDATION_WARNINGS]]
    assert reasons == ["invalid_ttl", "missing_or_invalid_magnitude"]


def test_phase2_repairs_null_on_tick_without_silently_passing_it():
    fighters = {
        C.FIGHTER_A: FighterState.from_preset(C.FIGHTER_A, "humanoid"),
        C.FIGHTER_B: FighterState.from_preset(C.FIGHTER_B, "humanoid"),
    }
    p1 = {f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True, f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": False}
    rolls = {C.FIGHTER_A: True, C.FIGHTER_B: False}
    p2 = {
        C.NARRATION: "A poisons B.",
        C.DELTA: {
            C.FIGHTER_B: {
                C.EFFECTS_ADDED: [
                    {
                        C.SOURCE: C.FIGHTER_A,
                        C.NAME: "poisoned",
                        C.VALUE: 2,
                        C.EFFECT_TTL: 3,
                        C.EFFECT_ON_APPLY: "Poison takes hold.",
                        C.EFFECT_ON_TICK: None,
                    }
                ]
            }
        },
        C.FIGHT_END: False,
        C.WINNER: None,
    }

    sanitized = sim_module._authorize_phase2_result(
        p2,
        p1,
        rolls,
        fighters,
        attempts={C.FIGHTER_A: "I poison my opponent.", C.FIGHTER_B: "I wait."},
    )

    effect = sanitized[C.DELTA][C.FIGHTER_B][C.EFFECTS_ADDED][0]
    assert effect[C.NAME] == "poisoned"
    assert C.EFFECT_ON_TICK not in effect
    assert sanitized[C.VALIDATION_WARNINGS][0]["reason"] == "null_on_tick_removed"


def test_phase2_drops_self_debuff_when_source_attempt_targeted_opponent():
    fighters = {
        C.FIGHTER_A: FighterState.from_preset(C.FIGHTER_A, "humanoid"),
        C.FIGHTER_B: FighterState.from_preset(C.FIGHTER_B, "humanoid"),
    }
    p1 = {f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": False, f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True}
    rolls = {C.FIGHTER_A: False, C.FIGHTER_B: True}
    p2 = {
        C.NARRATION: "B somehow poisons himself while attacking A.",
        C.DELTA: {
            C.FIGHTER_B: {
                C.EFFECTS_ADDED: [
                    {
                        C.SOURCE: C.FIGHTER_B,
                        C.NAME: "poisoned",
                        C.VALUE: 2,
                        C.EFFECT_TTL: 3,
                        C.TYPE: C.DEBUFFS,
                        C.EFFECT_ON_APPLY: "Poison takes hold.",
                    }
                ]
            }
        },
        C.FIGHT_END: False,
        C.WINNER: None,
    }

    sanitized = sim_module._authorize_phase2_result(
        p2,
        p1,
        rolls,
        fighters,
        attempts={C.FIGHTER_A: "I wait.", C.FIGHTER_B: "I stab my opponent with a poison dagger."},
    )

    assert sanitized[C.DELTA] == {}
    assert sanitized[C.VALIDATION_WARNINGS][0]["code"] == C.WARNING_CODE_P2_EFFECT_SOURCE_MISMATCH


def test_phase2_drops_self_debuff_when_source_attempt_names_opponent_id():
    fighters = {
        C.FIGHTER_A: FighterState.from_preset(C.FIGHTER_A, "humanoid"),
        C.FIGHTER_B: FighterState.from_preset(C.FIGHTER_B, "humanoid"),
    }
    p1 = {f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": False, f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True}
    rolls = {C.FIGHTER_A: False, C.FIGHTER_B: True}
    p2 = {
        C.NARRATION: "B somehow poisons himself while attacking A.",
        C.DELTA: {
            C.FIGHTER_B: {
                C.EFFECTS_ADDED: [
                    {
                        C.SOURCE: C.FIGHTER_B,
                        C.NAME: "poisoned",
                        C.VALUE: 2,
                        C.EFFECT_TTL: 3,
                        C.TYPE: C.DEBUFFS,
                        C.EFFECT_ON_APPLY: "Poison takes hold.",
                    }
                ]
            }
        },
        C.FIGHT_END: False,
        C.WINNER: None,
    }

    sanitized = sim_module._authorize_phase2_result(
        p2,
        p1,
        rolls,
        fighters,
        attempts={C.FIGHTER_A: "I wait.", C.FIGHTER_B: "I stab A with a poison dagger."},
    )

    assert sanitized[C.DELTA] == {}
    assert sanitized[C.VALIDATION_WARNINGS][0]["code"] == C.WARNING_CODE_P2_EFFECT_SOURCE_MISMATCH


def test_phase2_canonicalizes_effect_added_target_alias():
    fighters = {
        C.FIGHTER_A: FighterState.from_preset(C.FIGHTER_A, "humanoid"),
        C.FIGHTER_B: FighterState.from_preset(C.FIGHTER_B, "humanoid"),
    }
    p1 = {f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True, f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": False}
    rolls = {C.FIGHTER_A: True, C.FIGHTER_B: False}
    p2 = {
        C.NARRATION: "A poisons B's left arm.",
        C.DELTA: {
            C.FIGHTER_B: {
                C.EFFECTS_ADDED: [
                    {
                        C.SOURCE: C.FIGHTER_A,
                        C.NAME: "poisoned",
                        C.VALUE: 2,
                        C.EFFECT_TTL: 3,
                        C.TYPE: C.DEBUFFS,
                        C.EFFECT_ON_APPLY: "Poison takes hold.",
                        C.METADATA: {C.TARGETED_PART: "left arm"},
                    }
                ]
            }
        },
        C.FIGHT_END: False,
        C.WINNER: None,
    }

    sanitized = sim_module._authorize_phase2_result(
        p2,
        p1,
        rolls,
        fighters,
        attempts={C.FIGHTER_A: "I poison my opponent's left arm.", C.FIGHTER_B: "I wait."},
    )

    effect = sanitized[C.DELTA][C.FIGHTER_B][C.EFFECTS_ADDED][0]
    assert effect[C.METADATA][C.TARGETED_PART] == "left_arm"
    assert sanitized[C.VALIDATION_WARNINGS][0]["code"] == C.WARNING_CODE_CANONICALIZED_EFFECT_TARGET


def test_phase2_repairs_successful_custom_part_damage_from_unique_suffix():
    wing_profile = {
        C.CONFIG_FIGHTER_CLASS: "winged fighter",
        C.LOADOUT: "profile weapon",
        "environment": "profile arena",
        C.BODY_PARTS: [
            {"id": "left_wing", "layers": [{C.NAME: "feathers", C.MAX_HP: 12}]},
            {"id": "tail", "is_vital": True, "layers": [{C.NAME: "muscle", C.MAX_HP: 8}]},
        ],
    }
    fighters = {
        C.FIGHTER_A: FighterState.from_preset(C.FIGHTER_A, "humanoid"),
        C.FIGHTER_B: FighterState.from_profile(C.FIGHTER_B, build_fighter_profile(wing_profile)),
    }
    p1 = {f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True, f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": False}
    rolls = {C.FIGHTER_A: True, C.FIGHTER_B: False}
    p2 = {C.NARRATION: "A hits but the judge omits mechanics.", C.DELTA: {}, C.FIGHT_END: False, C.WINNER: None}

    sanitized = sim_module._authorize_phase2_result(
        p2,
        p1,
        rolls,
        fighters,
        attempts={C.FIGHTER_A: "I slash B's wing with my sword.", C.FIGHTER_B: "I wait."},
    )

    wound = sanitized[C.DELTA][C.FIGHTER_B][C.WOUNDS][0]
    assert wound[C.TARGETED_PART] == "left_wing"
    assert sanitized[C.VALIDATION_WARNINGS][0]["code"] == C.WARNING_CODE_P2_MECHANICAL_REPAIR


def test_phase2_warns_when_successful_custom_damage_has_no_resolvable_target():
    fighters = {
        C.FIGHTER_A: FighterState.from_preset(C.FIGHTER_A, "humanoid"),
        C.FIGHTER_B: FighterState.from_profile(C.FIGHTER_B, build_fighter_profile(_custom_profile("armor_core"))),
    }
    p1 = {f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True, f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": False}
    rolls = {C.FIGHTER_A: True, C.FIGHTER_B: False}
    p2 = {C.NARRATION: "A lands somewhere unclear.", C.DELTA: {}, C.FIGHT_END: True, C.WINNER: C.FIGHTER_A}

    sanitized = sim_module._authorize_phase2_result(
        p2,
        p1,
        rolls,
        fighters,
        attempts={C.FIGHTER_A: "I slash wildly at B.", C.FIGHTER_B: "I wait."},
    )

    assert sanitized[C.DELTA] == {}
    assert sanitized[C.FIGHT_END] is False
    assert sanitized[C.WINNER] is None
    assert sanitized[C.VALIDATION_WARNINGS][0]["code"] == C.WARNING_CODE_P2_NO_EFFECT
    assert sanitized[C.NARRATION] == (
        "A successful damage attempt had no resolvable target, so no mechanical effect was applied."
    )
