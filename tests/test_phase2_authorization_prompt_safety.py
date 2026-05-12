import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import llm_fight.simulation as sim_module
from llm_fight.config import CONFIG
from llm_fight.engine import constants as C


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
async def test_unauthorized_phase2_invalid_target_text_does_not_reach_prompts():
    invalid_target = "failed_roll_wing"
    fighter_recent_logs = []
    p1_recent_logs = []
    p2_recent_logs = []
    p1_calls = 0
    p2_calls = 0

    async def fake_get_attempt(fighter, opponent, combat_log=None, turn_window=0, **kwargs):
        if combat_log is not None:
            fighter_recent_logs.append(combat_log.to_summary(last_n=turn_window))
        return "attack"

    async def fake_judge_p1(*args, **kwargs):
        nonlocal p1_calls
        p1_calls += 1
        p1_recent_logs.append(kwargs.get("recent_log", ""))
        if p1_calls == 1:
            return {
                f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": False,
                f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "0.0",
                f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": False,
                f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
                "judgement_text": "Both attempts fail.",
                "explanation": "",
            }
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
                C.NARRATION: f"A's failed action somehow destroys B's {invalid_target}.",
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
    assert combat_log.turns[0].judge_p2[C.VALIDATION_WARNINGS][0]["code"] == C.WARNING_CODE_INVALID_P2_WOUND_TARGET
    assert invalid_target not in "\n".join(fighter_recent_logs[2:])
    assert invalid_target not in "\n".join(p1_recent_logs[1:])
    assert invalid_target not in "\n".join(p2_recent_logs[1:])


@pytest.mark.asyncio
async def test_unauthorized_phase2_invalid_effect_removal_target_text_does_not_reach_prompts():
    invalid_target = "failed_roll_wing_removal"
    fighter_recent_logs = []
    p1_recent_logs = []
    p2_recent_logs = []
    p1_calls = 0
    p2_calls = 0

    async def fake_get_attempt(fighter, opponent, combat_log=None, turn_window=0, **kwargs):
        if combat_log is not None:
            fighter_recent_logs.append(combat_log.to_summary(last_n=turn_window))
        return "attack"

    async def fake_judge_p1(*args, **kwargs):
        nonlocal p1_calls
        p1_calls += 1
        p1_recent_logs.append(kwargs.get("recent_log", ""))
        if p1_calls == 1:
            return {
                f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": False,
                f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "0.0",
                f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": False,
                f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
                "judgement_text": "Both attempts fail.",
                "explanation": "",
            }
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
                C.NARRATION: f"A's failed action somehow treats B's {invalid_target}.",
                C.DELTA: {
                    C.FIGHTER_B: {
                        C.EFFECTS_REMOVED: [
                            {
                                C.SOURCE: C.FIGHTER_A,
                                C.NAME: C.EFFECT_BLEEDING,
                                C.TARGETED_PART: invalid_target,
                            }
                        ]
                    }
                },
                C.FIGHT_END: True,
                C.WINNER: C.FIGHTER_A,
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
    assert (
        combat_log.turns[0].judge_p2[C.VALIDATION_WARNINGS][0]["code"] == C.WARNING_CODE_INVALID_EFFECT_REMOVAL_TARGET
    )
    assert combat_log.turns[0].judge_p2[C.FIGHT_END] is False
    assert combat_log.turns[0].judge_p2[C.WINNER] is None
    assert invalid_target not in "\n".join(fighter_recent_logs[2:])
    assert invalid_target not in "\n".join(p1_recent_logs[1:])
    assert invalid_target not in "\n".join(p2_recent_logs[1:])


@pytest.mark.asyncio
async def test_partially_authorized_invalid_target_text_does_not_reach_prompts():
    invalid_target = "failed_counter_wing"
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
            "judgement_text": "A succeeds while B fails.",
            "explanation": "",
        }

    async def fake_judge_p2(p2_input_state, *args, **kwargs):
        nonlocal p2_calls
        p2_calls += 1
        p2_recent_logs.append(p2_input_state.get("recent_combat_log", ""))
        if p2_calls == 1:
            return {
                C.NARRATION: f"B's failed counter somehow destroys A's {invalid_target}.",
                C.DELTA: {
                    C.FIGHTER_A: {
                        C.WOUNDS: [
                            {
                                C.SOURCE: C.FIGHTER_B,
                                C.TARGETED_PART: invalid_target,
                                C.VALUE: 999,
                                C.TYPE: C.DamageType.PIERCING,
                            }
                        ]
                    }
                },
                C.FIGHT_END: True,
                C.WINNER: C.FIGHTER_B,
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

    turn_p2 = combat_log.turns[0].judge_p2
    assert turn_p2[C.DELTA] == {}
    assert turn_p2[C.FIGHT_END] is False
    assert turn_p2[C.WINNER] is None
    assert turn_p2[C.VALIDATION_WARNINGS][0]["code"] == C.WARNING_CODE_INVALID_P2_WOUND_TARGET
    assert invalid_target not in json.dumps(turn_p2)
    assert invalid_target not in "\n".join(fighter_recent_logs[2:])
    assert invalid_target not in "\n".join(p1_recent_logs[1:])
    assert invalid_target not in "\n".join(p2_recent_logs[1:])


@pytest.mark.asyncio
async def test_partially_authorized_invalid_effect_removal_target_text_does_not_reach_prompts():
    invalid_target = "failed_counter_wing_removal"
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
            "judgement_text": "A succeeds while B fails.",
            "explanation": "",
        }

    async def fake_judge_p2(p2_input_state, *args, **kwargs):
        nonlocal p2_calls
        p2_calls += 1
        p2_recent_logs.append(p2_input_state.get("recent_combat_log", ""))
        if p2_calls == 1:
            return {
                C.NARRATION: f"B's failed counter somehow treats A's {invalid_target}.",
                C.DELTA: {
                    C.FIGHTER_A: {
                        C.EFFECTS_REMOVED: [
                            {
                                C.SOURCE: C.FIGHTER_B,
                                C.NAME: C.EFFECT_BLEEDING,
                                C.TARGETED_PART: invalid_target,
                            }
                        ]
                    }
                },
                C.FIGHT_END: True,
                C.WINNER: C.FIGHTER_B,
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

    turn_p2 = combat_log.turns[0].judge_p2
    assert turn_p2[C.DELTA] == {}
    assert turn_p2[C.FIGHT_END] is False
    assert turn_p2[C.WINNER] is None
    assert turn_p2[C.VALIDATION_WARNINGS][0]["code"] == C.WARNING_CODE_INVALID_EFFECT_REMOVAL_TARGET
    assert invalid_target not in json.dumps(turn_p2)
    assert invalid_target not in "\n".join(fighter_recent_logs[2:])
    assert invalid_target not in "\n".join(p1_recent_logs[1:])
    assert invalid_target not in "\n".join(p2_recent_logs[1:])
