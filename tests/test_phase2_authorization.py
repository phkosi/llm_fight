import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import llm_fight.simulation as sim_module
from llm_fight.config import CONFIG
from llm_fight.engine import constants as C
from llm_fight.profiles import build_fighter_profile
from llm_fight.state import Effect, FighterState


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


@pytest.mark.asyncio
async def test_phase2_invalid_wound_target_is_sanitized_before_apply_and_log():
    fighters = []
    original_from_preset = sim_module.FighterState.from_preset

    def capture_from_preset(id_, preset, config_section=None):
        fighter = original_from_preset(id_, preset, config_section=config_section)
        fighters.append(fighter)
        return fighter

    async def fake_judge_p1(*args, **kwargs):
        return {
            f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "1.0",
            f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
            "judgement_text": "A succeeds.",
            "explanation": "",
        }

    async def fake_judge_p2(*args, **kwargs):
        return {
            C.NARRATION: "A pierces B's impossible wing and wins.",
            C.DELTA: {
                C.FIGHTER_B: {
                    C.WOUNDS: [
                        {
                            C.SOURCE: C.FIGHTER_A,
                            C.TARGETED_PART: "wing",
                            C.VALUE: 999,
                            C.TYPE: C.DamageType.PIERCING,
                        }
                    ]
                }
            },
            C.FIGHT_END: True,
            C.WINNER: C.FIGHTER_A,
        }

    original_max_turns = CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, int, fallback=100)
    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, "1")

    try:
        with (
            patch.object(sim_module.FighterState, "from_preset", side_effect=capture_from_preset),
            patch.object(sim_module, "get_fighter_attempt", new=AsyncMock(return_value="attack")),
            patch.object(sim_module, "judge_phase1", new=AsyncMock(side_effect=fake_judge_p1)),
            patch.object(sim_module, "judge_phase2", new=AsyncMock(side_effect=fake_judge_p2)),
            patch.object(sim_module, "rand", MagicMock(return_value=0.0), create=True),
        ):
            result, combat_log = await sim_module._single_fight(return_log=True)
    finally:
        CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, str(original_max_turns))

    turn_p2 = combat_log.turns[0].judge_p2
    assert result[C.WINNER] == C.DRAW
    assert fighters[1].pain == 0
    assert turn_p2[C.DELTA] == {}
    assert turn_p2[C.FIGHT_END] is False
    assert turn_p2[C.WINNER] is None
    assert turn_p2[C.VALIDATION_WARNINGS][0]["code"] == C.WARNING_CODE_INVALID_P2_WOUND_TARGET
    assert "wing" not in json.dumps(turn_p2)


@pytest.mark.asyncio
async def test_phase2_wound_target_alias_canonicalizes_before_apply():
    fighters = []
    original_from_preset = sim_module.FighterState.from_preset

    def capture_from_preset(id_, preset, config_section=None):
        fighter = original_from_preset(id_, preset, config_section=config_section)
        fighters.append(fighter)
        return fighter

    async def fake_judge_p1(*args, **kwargs):
        return {
            f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "1.0",
            f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
            "judgement_text": "A succeeds.",
            "explanation": "",
        }

    async def fake_judge_p2(*args, **kwargs):
        return {
            C.NARRATION: "A clips B around the neck.",
            C.DELTA: {
                C.FIGHTER_B: {
                    C.WOUNDS: [
                        {
                            C.SOURCE: C.FIGHTER_A,
                            C.TARGETED_PART: "neck",
                            C.VALUE: 5,
                            C.TYPE: C.DamageType.BLUNT,
                        }
                    ]
                }
            },
            C.FIGHT_END: False,
            C.WINNER: None,
        }

    original_max_turns = CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, int, fallback=100)
    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, "1")

    try:
        with (
            patch.object(sim_module.FighterState, "from_preset", side_effect=capture_from_preset),
            patch.object(sim_module, "get_fighter_attempt", new=AsyncMock(return_value="attack")),
            patch.object(sim_module, "judge_phase1", new=AsyncMock(side_effect=fake_judge_p1)),
            patch.object(sim_module, "judge_phase2", new=AsyncMock(side_effect=fake_judge_p2)),
            patch.object(sim_module, "rand", MagicMock(return_value=0.0), create=True),
        ):
            _, combat_log = await sim_module._single_fight(return_log=True)
    finally:
        CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, str(original_max_turns))

    turn_p2 = combat_log.turns[0].judge_p2
    wound = turn_p2[C.DELTA][C.FIGHTER_B][C.WOUNDS][0]
    assert wound[C.TARGETED_PART] == "head"
    assert fighters[1].pain == 5
    assert turn_p2[C.VALIDATION_WARNINGS][0]["code"] == C.WARNING_CODE_CANONICALIZED_P2_WOUND_TARGET
    assert turn_p2[C.VALIDATION_WARNINGS][0]["canonical_part"] == "head"


@pytest.mark.asyncio
async def test_phase2_effect_removal_target_alias_canonicalizes_before_apply():
    fighters = []
    original_from_preset = sim_module.FighterState.from_preset

    def capture_from_preset(id_, preset, config_section=None):
        fighter = original_from_preset(id_, preset, config_section=config_section)
        if id_ == C.FIGHTER_B:
            fighter.debuffs.extend(
                [
                    Effect(
                        name=C.EFFECT_BLEEDING,
                        magnitude=1,
                        ttl=3,
                        on_apply="Left arm bleeds.",
                        metadata={C.TARGETED_PART: "left_arm"},
                    ),
                    Effect(
                        name=C.EFFECT_BLEEDING,
                        magnitude=1,
                        ttl=3,
                        on_apply="Right arm bleeds.",
                        metadata={C.TARGETED_PART: "right_arm"},
                    ),
                ]
            )
        fighters.append(fighter)
        return fighter

    async def fake_judge_p1(*args, **kwargs):
        return {
            f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "1.0",
            f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
            "judgement_text": "A succeeds.",
            "explanation": "",
        }

    async def fake_judge_p2(*args, **kwargs):
        return {
            C.NARRATION: "A staunches B's left arm.",
            C.DELTA: {
                C.FIGHTER_B: {
                    C.EFFECTS_REMOVED: [
                        {
                            C.SOURCE: C.FIGHTER_A,
                            C.NAME: C.EFFECT_BLEEDING,
                            C.TYPE: C.DEBUFFS,
                            C.TARGETED_PART: "left arm",
                        }
                    ]
                }
            },
            C.FIGHT_END: False,
            C.WINNER: None,
        }

    original_max_turns = CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, int, fallback=100)
    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, "1")

    try:
        with (
            patch.object(sim_module.FighterState, "from_preset", side_effect=capture_from_preset),
            patch.object(sim_module, "get_fighter_attempt", new=AsyncMock(return_value="attack")),
            patch.object(sim_module, "judge_phase1", new=AsyncMock(side_effect=fake_judge_p1)),
            patch.object(sim_module, "judge_phase2", new=AsyncMock(side_effect=fake_judge_p2)),
            patch.object(sim_module, "rand", MagicMock(return_value=0.0), create=True),
        ):
            _, combat_log = await sim_module._single_fight(return_log=True)
    finally:
        CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, str(original_max_turns))

    turn_p2 = combat_log.turns[0].judge_p2
    removal = turn_p2[C.DELTA][C.FIGHTER_B][C.EFFECTS_REMOVED][0]
    assert removal == {C.NAME: C.EFFECT_BLEEDING, C.TYPE: C.DEBUFFS, C.TARGETED_PART: "left_arm"}
    assert [eff.metadata[C.TARGETED_PART] for eff in fighters[1].debuffs] == ["right_arm"]
    assert turn_p2[C.VALIDATION_WARNINGS][0]["code"] == C.WARNING_CODE_CANONICALIZED_EFFECT_REMOVAL_TARGET
    assert turn_p2[C.VALIDATION_WARNINGS][0]["canonical_part"] == "left_arm"


@pytest.mark.asyncio
async def test_phase2_invalid_effect_removal_target_is_dropped():
    fighters = []
    original_from_preset = sim_module.FighterState.from_preset

    def capture_from_preset(id_, preset, config_section=None):
        fighter = original_from_preset(id_, preset, config_section=config_section)
        if id_ == C.FIGHTER_B:
            fighter.debuffs.append(
                Effect(
                    name=C.EFFECT_BLEEDING,
                    magnitude=1,
                    ttl=3,
                    on_apply="Left arm bleeds.",
                    metadata={C.TARGETED_PART: "left_arm"},
                )
            )
        fighters.append(fighter)
        return fighter

    async def fake_judge_p1(*args, **kwargs):
        return {
            f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "1.0",
            f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
            "judgement_text": "A succeeds.",
            "explanation": "",
        }

    async def fake_judge_p2(*args, **kwargs):
        return {
            C.NARRATION: "A treats a nonexistent wing.",
            C.DELTA: {
                C.FIGHTER_B: {
                    C.EFFECTS_REMOVED: [
                        {
                            C.SOURCE: C.FIGHTER_A,
                            C.NAME: C.EFFECT_BLEEDING,
                            C.TARGETED_PART: "wing",
                        }
                    ]
                }
            },
            C.FIGHT_END: False,
            C.WINNER: None,
        }

    original_max_turns = CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, int, fallback=100)
    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, "1")

    try:
        with (
            patch.object(sim_module.FighterState, "from_preset", side_effect=capture_from_preset),
            patch.object(sim_module, "get_fighter_attempt", new=AsyncMock(return_value="attack")),
            patch.object(sim_module, "judge_phase1", new=AsyncMock(side_effect=fake_judge_p1)),
            patch.object(sim_module, "judge_phase2", new=AsyncMock(side_effect=fake_judge_p2)),
            patch.object(sim_module, "rand", MagicMock(return_value=0.0), create=True),
        ):
            _, combat_log = await sim_module._single_fight(return_log=True)
    finally:
        CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, str(original_max_turns))

    turn_p2 = combat_log.turns[0].judge_p2
    assert turn_p2[C.DELTA] == {}
    assert [eff.metadata[C.TARGETED_PART] for eff in fighters[1].debuffs] == ["left_arm"]
    assert turn_p2[C.VALIDATION_WARNINGS][0]["code"] == C.WARNING_CODE_INVALID_EFFECT_REMOVAL_TARGET
    assert "wing" not in json.dumps(turn_p2)


@pytest.mark.asyncio
async def test_phase2_mixed_valid_and_invalid_wounds_apply_only_valid_target():
    fighters = []
    original_from_preset = sim_module.FighterState.from_preset

    def capture_from_preset(id_, preset, config_section=None):
        fighter = original_from_preset(id_, preset, config_section=config_section)
        fighters.append(fighter)
        return fighter

    async def fake_judge_p1(*args, **kwargs):
        return {
            f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "1.0",
            f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
            "judgement_text": "A succeeds.",
            "explanation": "",
        }

    async def fake_judge_p2(*args, **kwargs):
        return {
            C.NARRATION: "A bruises B's torso, while the wing reference is impossible.",
            C.DELTA: {
                C.FIGHTER_B: {
                    C.WOUNDS: [
                        {
                            C.SOURCE: C.FIGHTER_A,
                            C.TARGETED_PART: "torso",
                            C.VALUE: 5,
                            C.TYPE: C.DamageType.BLUNT,
                        },
                        {
                            C.SOURCE: C.FIGHTER_A,
                            C.TARGETED_PART: "wing",
                            C.VALUE: 999,
                            C.TYPE: C.DamageType.PIERCING,
                        },
                    ]
                }
            },
            C.FIGHT_END: True,
            C.WINNER: C.FIGHTER_A,
        }

    original_max_turns = CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, int, fallback=100)
    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, "1")

    try:
        with (
            patch.object(sim_module.FighterState, "from_preset", side_effect=capture_from_preset),
            patch.object(sim_module, "get_fighter_attempt", new=AsyncMock(return_value="attack")),
            patch.object(sim_module, "judge_phase1", new=AsyncMock(side_effect=fake_judge_p1)),
            patch.object(sim_module, "judge_phase2", new=AsyncMock(side_effect=fake_judge_p2)),
            patch.object(sim_module, "rand", MagicMock(return_value=0.0), create=True),
        ):
            result, combat_log = await sim_module._single_fight(return_log=True)
    finally:
        CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, str(original_max_turns))

    turn_p2 = combat_log.turns[0].judge_p2
    wounds = turn_p2[C.DELTA][C.FIGHTER_B][C.WOUNDS]
    assert result[C.WINNER] == C.DRAW
    assert [wound[C.TARGETED_PART] for wound in wounds] == ["torso"]
    assert fighters[1].pain == 5
    assert turn_p2[C.VALIDATION_WARNINGS][0]["code"] == C.WARNING_CODE_INVALID_P2_WOUND_TARGET
    assert "wing" not in json.dumps(turn_p2)


@pytest.mark.asyncio
async def test_phase2_invalid_target_text_does_not_reach_next_turn_prompts():
    invalid_target = "obsidian_wing_needle"
    fighter_recent_logs = []
    p1_recent_logs = []
    p2_recent_logs = []
    p2_calls = 0

    async def fake_get_attempt(fighter, opponent, combat_log=None, turn_window=0, **kwargs):
        if combat_log is not None:
            fighter_recent_logs.append(combat_log.to_summary(last_n=turn_window))
        return "attack"

    async def fake_judge_p1(*args, **kwargs):
        p1_recent_logs.append(kwargs.get("recent_log", ""))
        return {
            f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "1.0",
            f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
            "judgement_text": "A succeeds.",
            "explanation": "",
        }

    async def fake_judge_p2(p2_input_state, *args, **kwargs):
        nonlocal p2_calls
        p2_calls += 1
        p2_recent_logs.append(p2_input_state.get("recent_combat_log", ""))
        if p2_calls == 1:
            return {
                C.NARRATION: f"A strikes the invalid {invalid_target}.",
                C.DELTA: {
                    C.FIGHTER_B: {
                        C.WOUNDS: [
                            {
                                C.SOURCE: C.FIGHTER_A,
                                C.TARGETED_PART: invalid_target,
                                C.VALUE: 999,
                                C.TYPE: C.DamageType.PIERCING,
                            }
                        ]
                    }
                },
                C.FIGHT_END: True,
                C.WINNER: C.FIGHTER_A,
                "unsafe_extra": invalid_target,
            }
        return {C.NARRATION: "Both fighters reset.", C.DELTA: {}, C.FIGHT_END: False, C.WINNER: None}

    original_max_turns = CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, int, fallback=100)
    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, "2")

    try:
        with (
            patch.object(sim_module, "get_fighter_attempt", new=AsyncMock(side_effect=fake_get_attempt)),
            patch.object(sim_module, "judge_phase1", new=AsyncMock(side_effect=fake_judge_p1)),
            patch.object(sim_module, "judge_phase2", new=AsyncMock(side_effect=fake_judge_p2)),
            patch.object(sim_module, "rand", MagicMock(return_value=0.0), create=True),
        ):
            _, combat_log = await sim_module._single_fight(return_log=True)
    finally:
        CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, str(original_max_turns))

    assert invalid_target not in json.dumps(combat_log.turns[0].judge_p2)
    assert invalid_target not in "\n".join(fighter_recent_logs[2:])
    assert invalid_target not in "\n".join(p1_recent_logs[1:])
    assert invalid_target not in "\n".join(p2_recent_logs[1:])


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
