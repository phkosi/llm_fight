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


def test_phase2_target_validation_is_scoped_to_target_fighter_anatomy():
    humanoid = FighterState.from_preset(C.FIGHTER_A, "humanoid")
    winged = FighterState.from_profile(
        C.FIGHTER_B,
        build_fighter_profile(_custom_profile("wing")),
        allow_config_overrides=False,
    )
    p1 = {
        f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
        f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": False,
    }
    rolls = {C.FIGHTER_A: True, C.FIGHTER_B: False}
    p2 = {
        C.NARRATION: "A tests both wing targets.",
        C.DELTA: {
            C.FIGHTER_A: {
                C.WOUNDS: [
                    {
                        C.SOURCE: C.FIGHTER_A,
                        C.TARGETED_PART: "wing",
                        C.VALUE: 5,
                        C.TYPE: C.DamageType.PIERCING,
                    }
                ]
            },
            C.FIGHTER_B: {
                C.WOUNDS: [
                    {
                        C.SOURCE: C.FIGHTER_A,
                        C.TARGETED_PART: "wing",
                        C.VALUE: 5,
                        C.TYPE: C.DamageType.PIERCING,
                    }
                ]
            },
        },
        C.FIGHT_END: False,
        C.WINNER: None,
    }

    sanitized = sim_module._authorize_phase2_result(
        p2,
        p1,
        rolls,
        {C.FIGHTER_A: humanoid, C.FIGHTER_B: winged},
    )

    assert C.FIGHTER_A not in sanitized[C.DELTA]
    assert sanitized[C.DELTA][C.FIGHTER_B][C.WOUNDS][0][C.TARGETED_PART] == "wing"
    assert sanitized[C.VALIDATION_WARNINGS][0]["fighter_id"] == C.FIGHTER_A
    assert sanitized[C.VALIDATION_WARNINGS][0]["code"] == C.WARNING_CODE_INVALID_P2_WOUND_TARGET


def test_phase2_drops_self_targeted_wound_when_source_attempt_hits_opponent():
    fighters = {
        C.FIGHTER_A: FighterState.from_preset(C.FIGHTER_A, "humanoid"),
        C.FIGHTER_B: FighterState.from_preset(C.FIGHTER_B, "humanoid"),
    }
    fighters[C.FIGHTER_A].display_name = "Sir Galant"
    fighters[C.FIGHTER_B].display_name = "Shade"
    p1 = {
        f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
        f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": False,
    }
    rolls = {C.FIGHTER_A: True, C.FIGHTER_B: False}
    p2 = {
        C.NARRATION: "A cuts B, but the delta points at A.",
        C.DELTA: {
            C.FIGHTER_A: {
                C.WOUNDS: [
                    {
                        C.SOURCE: C.FIGHTER_A,
                        C.TARGETED_PART: "torso",
                        C.VALUE: 50,
                        C.TYPE: C.DamageType.SLASHING,
                    }
                ]
            }
        },
        C.FIGHT_END: True,
        C.WINNER: C.FIGHTER_A,
    }

    sanitized = sim_module._authorize_phase2_result(
        p2,
        p1,
        rolls,
        fighters,
        attempts={
            C.FIGHTER_A: "I slash Shade's torso with my longsword.",
            C.FIGHTER_B: "I circle away.",
        },
    )

    assert C.FIGHTER_A not in sanitized[C.DELTA]
    wound = sanitized[C.DELTA][C.FIGHTER_B][C.WOUNDS][0]
    assert wound[C.TARGETED_PART] == "torso"
    assert sanitized[C.FIGHT_END] is False
    assert sanitized[C.WINNER] is None
    warning_codes = [warning["code"] for warning in sanitized[C.VALIDATION_WARNINGS]]
    assert C.WARNING_CODE_P2_WOUND_SOURCE_MISMATCH in warning_codes
    assert C.WARNING_CODE_P2_MECHANICAL_REPAIR in warning_codes


def test_phase2_canonicalizes_wound_to_source_attempt_called_shot():
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
        C.NARRATION: "B strikes A's left arm, but the delta says torso.",
        C.DELTA: {
            C.FIGHTER_A: {
                C.WOUNDS: [
                    {
                        C.SOURCE: C.FIGHTER_B,
                        C.TARGETED_PART: "torso",
                        C.VALUE: 20,
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
            C.FIGHTER_A: "I brace behind my shield.",
            C.FIGHTER_B: "I stab Sir Galant's left arm with my dagger.",
        },
    )

    wound = sanitized[C.DELTA][C.FIGHTER_A][C.WOUNDS][0]
    assert wound[C.TARGETED_PART] == "left_arm"
    assert sanitized[C.VALIDATION_WARNINGS][0]["code"] == C.WARNING_CODE_CANONICALIZED_P2_WOUND_TARGET
    assert sanitized[C.VALIDATION_WARNINGS][0]["reason"] == "source_attempt_named_different_target"


def test_phase2_drops_wound_when_source_attempt_has_no_damage_intent():
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
        C.NARRATION: "B throws smoke, but the delta records a head wound.",
        C.DELTA: {
            C.FIGHTER_A: {
                C.WOUNDS: [
                    {
                        C.SOURCE: C.FIGHTER_B,
                        C.TARGETED_PART: "head",
                        C.VALUE: 1,
                        C.TYPE: C.DamageType.SLASHING,
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
            C.FIGHTER_A: "I close distance carefully.",
            C.FIGHTER_B: "I throw a smoke bomb at Sir Galant's face.",
        },
    )

    assert C.WOUNDS not in sanitized[C.DELTA][C.FIGHTER_A]
    assert sanitized[C.DELTA][C.FIGHTER_A][C.EFFECTS_ADDED][0][C.NAME] == "obscured"
    warning_codes = [warning["code"] for warning in sanitized[C.VALIDATION_WARNINGS]]
    assert C.WARNING_CODE_P2_WOUND_WITHOUT_DAMAGE_INTENT in warning_codes
    assert C.WARNING_CODE_P2_MECHANICAL_REPAIR in warning_codes


def test_phase2_drops_wound_when_damage_type_conflicts_with_source_attempt():
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
        C.NARRATION: "Shade gets behind Sir Galant and fire erupts from nowhere.",
        C.DELTA: {
            C.FIGHTER_A: {
                C.WOUNDS: [
                    {
                        C.SOURCE: C.FIGHTER_B,
                        C.TARGETED_PART: "torso",
                        C.VALUE: 50,
                        C.TYPE: C.DamageType.FIRE,
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
            C.FIGHTER_B: "I move behind Sir Galant for a strike with my poison dagger.",
        },
    )

    assert C.WOUNDS not in sanitized[C.DELTA][C.FIGHTER_A]
    assert sanitized[C.DELTA][C.FIGHTER_A][C.EFFECTS_ADDED][0][C.NAME] == "flanked"
    warning_codes = [warning["code"] for warning in sanitized[C.VALIDATION_WARNINGS]]
    assert C.WARNING_CODE_P2_WOUND_TYPE_MISMATCH in warning_codes
    assert C.WARNING_CODE_P2_MECHANICAL_REPAIR in warning_codes


def test_phase2_repairs_missing_wound_from_successful_called_shot():
    fighters = {
        C.FIGHTER_A: FighterState.from_preset(C.FIGHTER_A, "humanoid"),
        C.FIGHTER_B: FighterState.from_preset(C.FIGHTER_B, "humanoid"),
    }
    p1 = {
        f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
        f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": False,
    }
    rolls = {C.FIGHTER_A: True, C.FIGHTER_B: False}
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
            C.FIGHTER_A: "I strike Shade's left arm with my longsword.",
            C.FIGHTER_B: "I step back.",
        },
    )

    wound = sanitized[C.DELTA][C.FIGHTER_B][C.WOUNDS][0]
    assert wound == {
        C.TARGETED_PART: "left_arm",
        C.VALUE: 10,
        C.TYPE: C.DamageType.SLASHING,
    }
    assert sanitized[C.METADATA][C.P2_ENGINE_REPAIR_USED] is True
    assert sanitized[C.VALIDATION_WARNINGS][0]["code"] == C.WARNING_CODE_P2_MECHANICAL_REPAIR
    assert "left arm" in sanitized[C.NARRATION]


def test_phase2_replaces_narration_that_contradicts_successful_rolls():
    fighters = {
        C.FIGHTER_A: FighterState.from_preset(C.FIGHTER_A, "humanoid"),
        C.FIGHTER_B: FighterState.from_preset(C.FIGHTER_B, "humanoid"),
    }
    fighters[C.FIGHTER_A].display_name = C.FIGHTER_A
    fighters[C.FIGHTER_B].display_name = C.FIGHTER_B
    p1 = {
        f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
        f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
    }
    rolls = {C.FIGHTER_A: True, C.FIGHTER_B: True}
    p2 = {
        C.NARRATION: "Sir Galant lands a hit. Fighter B moves in but fails to land a hit.",
        C.DELTA: {
            C.FIGHTER_A: {
                C.WOUNDS: [
                    {
                        C.SOURCE: C.FIGHTER_B,
                        C.TARGETED_PART: "torso",
                        C.VALUE: 5,
                        C.TYPE: C.DamageType.PIERCING,
                    }
                ]
            },
            C.FIGHTER_B: {
                C.WOUNDS: [
                    {
                        C.SOURCE: C.FIGHTER_A,
                        C.TARGETED_PART: "torso",
                        C.VALUE: 5,
                        C.TYPE: C.DamageType.SLASHING,
                    }
                ]
            },
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
            C.FIGHTER_A: "I slash Shade's torso with my longsword.",
            C.FIGHTER_B: "I stab Sir Galant's torso with my dagger.",
        },
    )

    assert "fails" not in sanitized[C.NARRATION]
    assert "A's torso" in sanitized[C.NARRATION]
    assert sanitized[C.VALIDATION_WARNINGS][0]["code"] == C.WARNING_CODE_P2_NARRATION_ROLL_MISMATCH
