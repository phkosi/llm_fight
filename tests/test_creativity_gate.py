import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import llm_fight.simulation as sim_module
from llm_fight.anatomy import PRESETS, BodyPart, TissueLayer
from llm_fight.config import Config
from llm_fight.engine import constants as C
from llm_fight.engine.combat_log import CombatLog
from llm_fight.engine.fighter import get_fighter_attempt
from llm_fight.judge import judge_phase1
from llm_fight.state import FighterState


def _creative_profile():
    return {
        C.CONFIG_FIGHTER_CLASS: "Two-Headed Wingblade",
        C.THEME: "sky mutant",
        C.LOADOUT: "paired hook blades and wing spurs",
        "environment": "an open arena",
        C.BODY_PARTS: [
            {
                "id": "second_head",
                C.NAME: "second head",
                "is_vital": True,
                "layers": [{C.NAME: "bone", C.MAX_HP: 10}],
            },
            {
                "id": "left_wing",
                C.NAME: "left wing",
                "can_be_severed": True,
                C.BLEED_RATE: 2,
                "layers": [
                    {C.NAME: "feathers", C.MAX_HP: 8},
                    {C.NAME: "muscle", C.MAX_HP: 12},
                ],
            },
            {
                "id": "tentacle_1",
                C.NAME: "tentacle 1",
                "can_be_severed": True,
                "layers": [{C.NAME: "muscle", C.MAX_HP: 14}],
            },
        ],
    }


@pytest.mark.asyncio
async def test_non_humanoid_anatomy_survives_state_prompts_judge_and_log(tmp_path):
    profile_path = tmp_path / "creative_profile.json"
    profile_path.write_text(json.dumps(_creative_profile()), encoding="utf-8")
    config_path = tmp_path / "game.ini"
    config_path.write_text(
        "\n".join(
            [
                "[General]",
                "fighter_A = A",
                "fighter_B = B",
                "",
                "[SIMULATION]",
                "max_turns = 1",
                "",
                "[A]",
                f"anatomy_profile = {profile_path.name}",
            ]
        ),
        encoding="utf-8",
    )

    assert "left_wing" not in PRESETS["humanoid"].parts
    captured_fighter_prompts = []
    captured_p1_states = []
    captured_p2_inputs = []

    async def fake_get_attempt(fighter, opponent, combat_log=None, turn_window=0):
        prompt_log = CombatLog() if combat_log is None else combat_log
        with patch("llm_fight.engine.fighter.chat", new=AsyncMock(return_value=["I strike."])) as mock_chat:
            await get_fighter_attempt(fighter, opponent, combat_log=prompt_log, turn_window=turn_window)
        captured_fighter_prompts.append(mock_chat.call_args[0][0][0][C.AGENT_CONTENT])
        return "I strike."

    async def fake_judge_p1(state, *args, **kwargs):
        captured_p1_states.append(state)
        return {
            f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "0.0",
            f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
            "judgement_text": "Both fighters test range.",
            "explanation": "",
        }

    async def fake_judge_p2(p2_input, *args, **kwargs):
        captured_p2_inputs.append(p2_input)
        return {C.NARRATION: "They circle.", C.DELTA: {}, C.FIGHT_END: False, C.WINNER: None}

    old_config = sim_module.config_mod.CONFIG
    sim_module.config_mod.CONFIG = Config(config_path)
    try:
        with (
            patch.object(sim_module, "get_fighter_attempt", new=AsyncMock(side_effect=fake_get_attempt)),
            patch.object(sim_module, "judge_phase1", new=AsyncMock(side_effect=fake_judge_p1)),
            patch.object(sim_module, "judge_phase2", new=AsyncMock(side_effect=fake_judge_p2)),
        ):
            result, combat_log = await sim_module._single_fight(return_log=True)
    finally:
        sim_module.config_mod.CONFIG = old_config

    assert result[C.WINNER] == C.DRAW
    assert "left_wing" in captured_p1_states[0][C.FIGHTER_A]["parts"]
    assert "second_head" in captured_p1_states[0][C.FIGHTER_A]["parts"]
    assert "Your valid target parts: left_wing, second_head, tentacle_1" in captured_fighter_prompts[0]
    assert "left_wing" in captured_p2_inputs[0]["valid_target_parts"][C.FIGHTER_A]
    assert "left_wing" in combat_log.turns[0].state_A_before["parts"]
    assert "tentacle_1" in combat_log.turns[0].state_A_after["parts"]


@pytest.mark.asyncio
async def test_non_hard_coded_declarative_effect_survives_prompts_ticks_and_expires():
    fighter = FighterState(
        id=C.FIGHTER_A,
        parts={
            "crystal_core": BodyPart("crystal core", [TissueLayer("crystal", 20)], is_vital=True),
            "left_wing": BodyPart("left wing", [TissueLayer("feathers", 8)], can_be_severed=True),
        },
    )
    opponent = FighterState.from_preset(C.FIGHTER_B, "humanoid")
    assert "crystal_rot" not in {C.EFFECT_BLEEDING, C.EFFECT_BURNING, C.EFFECT_STUNNED}

    fighter.apply_delta(
        {
            C.EFFECTS_ADDED: [
                {
                    C.NAME: "crystal_rot",
                    C.VALUE: 3,
                    C.EFFECT_TTL: 2,
                    C.EFFECT_ON_APPLY: "Crystal rot spreads",
                    C.EFFECT_ON_TICK: "Crystal rot grinds the core",
                    C.METADATA: {C.TARGETED_PART: "crystal_core"},
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
        }
    )
    assert fighter.debuffs[0].name == "crystal_rot"
    assert fighter.debuffs[0].fresh_turns == 1
    state_effect = fighter.to_json()[C.DEBUFFS][0]
    assert state_effect[C.EFFECT_MECHANICS][0][C.EFFECT_MECHANIC_KIND] == C.EFFECT_MECHANIC_STAT_TICK
    assert state_effect[C.EFFECT_TAGS] == ["corrosion", "crystal"]

    captured_fighter_prompts = []
    captured_judge_payloads = []

    with patch("llm_fight.engine.fighter.chat", new=AsyncMock(return_value=["I guard."])) as mock_fighter_chat:
        await get_fighter_attempt(fighter, opponent, combat_log="", turn_window=0)
    captured_fighter_prompts.append(mock_fighter_chat.call_args[0][0][0][C.AGENT_CONTENT])

    async def mock_guarded_call(call_func, schema, max_retries=None):
        return await call_func()

    with (
        patch("llm_fight.judge.chat", new=AsyncMock(return_value=[json.dumps(_phase1_ok())])) as mock_judge_chat,
        patch("llm_fight.judge.guarded_call", new=AsyncMock(side_effect=mock_guarded_call)),
    ):
        await judge_phase1({C.FIGHTER_A: fighter.to_json(), C.FIGHTER_B: opponent.to_json()}, "A waits.", "B waits.")
    captured_judge_payloads.append(json.loads(mock_judge_chat.call_args[0][0][1][C.AGENT_CONTENT]))

    fighter.apply_effects()
    assert fighter.pain == 0
    assert fighter.debuffs[0].ttl == 2
    assert fighter.debuffs[0].fresh_turns == 0

    fighter.apply_effects()
    assert fighter.pain == 3
    assert fighter.debuffs[0].ttl == 1

    fighter.apply_effects()
    assert fighter.pain == 6
    assert fighter.debuffs == []

    prompt_text = captured_fighter_prompts[0]
    debuff_payload = captured_judge_payloads[0][f"fighter_{C.FIGHTER_A}_state_summary"][C.DEBUFFS][0]
    assert "crystal_rot" in prompt_text
    assert C.EFFECT_MECHANICS in prompt_text
    assert "corrosion" in prompt_text
    assert debuff_payload[C.NAME] == "crystal_rot"
    assert debuff_payload[C.EFFECT_MECHANICS][0][C.EFFECT_MECHANIC_KIND] == C.EFFECT_MECHANIC_STAT_TICK
    assert debuff_payload[C.EFFECT_TAGS] == ["corrosion", "crystal"]


def test_creativity_gate_doc_is_opt_in_and_outside_default_pytest():
    text = (Path(__file__).resolve().parents[1] / "docs" / "CREATIVITY_GATE.md").read_text(encoding="utf-8")

    assert "opt-in" in text
    assert "not part of default `pytest`" in text
    assert "Codex/manual reviewer prompt" in text


def _phase1_ok():
    return {
        "judgement_text": "Both actions are possible.",
        f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
        f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "0.5",
        f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
        f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.5",
        "explanation": "",
    }
