import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import llm_fight.simulation as sim_module
from llm_fight.config import CONFIG
from llm_fight.engine import constants as C
from llm_fight.state import Effect


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
