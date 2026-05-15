import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import llm_fight.simulation as sim_module
from llm_fight.agents import ChatResult
from llm_fight.config import CONFIG

# from llm_fight.anatomy import PRESETS as ANATOMY_PRESETS # No longer needed for this test's mocking strategy
from llm_fight.engine import constants as C
from llm_fight.state import Effect, FighterState  # Keep for spec


def _source_value(source=C.FIGHTER_A, value=1):
    return {C.SOURCE: source, C.VALUE: value}


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


def _write_profile(path, profile):
    path.write_text(json.dumps(profile), encoding="utf-8")
    return path


@pytest.mark.asyncio
async def test_targeting_modifier_reduces_success_probability_before_roll():
    fighter_a = FighterState.from_preset(C.FIGHTER_A, "humanoid")
    fighter_b = FighterState.from_preset(C.FIGHTER_B, "humanoid")
    fighter_a.debuffs.append(
        Effect(
            name="blinded",
            magnitude=1,
            ttl=2,
            on_apply="Eyes are obscured",
            mechanics=[
                {
                    C.EFFECT_MECHANIC_KIND: C.EFFECT_MECHANIC_TARGETING_MODIFIER,
                    C.EFFECT_MECHANIC_MODIFIER: C.EFFECT_MECHANIC_OUTGOING_ACCURACY_PENALTY,
                    C.VALUE: 100,
                }
            ],
        )
    )

    p2_inputs = []

    async def fake_judge_p1(*args, **kwargs):
        return {
            f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "1.0",
            f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": False,
            f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
            "judgement_text": "A would hit if not blinded.",
            "explanation": "",
        }

    async def fake_judge_p2(p2_input, *args, **kwargs):
        p2_inputs.append(p2_input)
        return {
            C.NARRATION: "A should not land this hit.",
            C.DELTA: {C.FIGHTER_B: {C.PAIN_INCREASE: _source_value(C.FIGHTER_A, 50)}},
            C.FIGHT_END: True,
            C.WINNER: C.FIGHTER_A,
        }

    original_max_turns = CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, int, fallback=100)
    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, "1")

    with (
        patch.object(sim_module.FighterState, "from_config", side_effect=[fighter_a, fighter_b]),
        patch.object(sim_module, "get_fighter_attempt", new=AsyncMock(return_value="attack")),
        patch.object(sim_module, "judge_phase1", new=AsyncMock(side_effect=fake_judge_p1)),
        patch.object(sim_module, "judge_phase2", new=AsyncMock(side_effect=fake_judge_p2)),
        patch.object(sim_module, "rand", MagicMock(return_value=0.0), create=True),
    ):
        result = await sim_module._single_fight()

    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, str(original_max_turns))

    assert result[C.WINNER] == C.DRAW
    assert fighter_b.pain == 0
    assert p2_inputs[0]["p1_result"][f"{C.ATTEMPT}_{C.FIGHTER_A}_prob"] == "0.0"
    assert C.EFFECT_MODIFIERS_APPLIED in p2_inputs[0]["p1_result"]


@pytest.mark.asyncio
async def test_action_modifier_invalidates_blocked_action_before_roll():
    fighter_a = FighterState.from_preset(C.FIGHTER_A, "humanoid")
    fighter_b = FighterState.from_preset(C.FIGHTER_B, "humanoid")
    fighter_a.debuffs.append(
        Effect(
            name="entangled",
            magnitude=1,
            ttl=2,
            on_apply="Vines bind the fighter",
            mechanics=[
                {
                    C.EFFECT_MECHANIC_KIND: C.EFFECT_MECHANIC_ACTION_MODIFIER,
                    C.EFFECT_MECHANIC_MODIFIER: C.EFFECT_MECHANIC_ACTION_BLOCK,
                    C.VALUE: 1,
                }
            ],
        )
    )

    p2_inputs = []

    async def fake_judge_p1(*args, **kwargs):
        return {
            f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "1.0",
            f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": False,
            f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
            "judgement_text": "A is entangled.",
            "explanation": "",
        }

    async def fake_judge_p2(p2_input, *args, **kwargs):
        p2_inputs.append(p2_input)
        return {
            C.NARRATION: "A should not act through the entanglement.",
            C.DELTA: {C.FIGHTER_B: {C.PAIN_INCREASE: _source_value(C.FIGHTER_A, 50)}},
            C.FIGHT_END: True,
            C.WINNER: C.FIGHTER_A,
        }

    original_max_turns = CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, int, fallback=100)
    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, "1")

    with (
        patch.object(sim_module.FighterState, "from_config", side_effect=[fighter_a, fighter_b]),
        patch.object(sim_module, "get_fighter_attempt", new=AsyncMock(return_value="attack")),
        patch.object(sim_module, "judge_phase1", new=AsyncMock(side_effect=fake_judge_p1)),
        patch.object(sim_module, "judge_phase2", new=AsyncMock(side_effect=fake_judge_p2)),
        patch.object(sim_module, "rand", MagicMock(return_value=0.0), create=True),
    ):
        result = await sim_module._single_fight()

    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, str(original_max_turns))

    assert result[C.WINNER] == C.DRAW
    assert fighter_b.pain == 0
    assert p2_inputs[0]["p1_result"][f"{C.ATTEMPT}_{C.FIGHTER_A}_valid"] is False
    assert p2_inputs[0]["p1_result"][f"{C.ATTEMPT}_{C.FIGHTER_A}_prob"] == "0.0"
    assert C.EFFECT_MODIFIERS_APPLIED in p2_inputs[0]["p1_result"]


@pytest.mark.asyncio
async def test_single_fight_uses_one_fixed_ollama_context_for_all_native_calls():
    old_values = {
        (C.CONFIG_GENERAL, C.CONFIG_LLAMA_DEFAULT_MODEL): CONFIG.get(
            C.CONFIG_GENERAL, C.CONFIG_LLAMA_DEFAULT_MODEL, str
        ),
        (C.CONFIG_GENERAL, C.CONFIG_OLLAMA_NUM_CTX): CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_OLLAMA_NUM_CTX, str),
        (C.CONFIG_GENERAL, C.CONFIG_OLLAMA_KEEP_ALIVE): CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_OLLAMA_KEEP_ALIVE, str),
        (C.CONFIG_GENERAL, C.CONFIG_MAX_TOKENS_FIGHTER): CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_MAX_TOKENS_FIGHTER, str),
        (C.CONFIG_GENERAL, C.CONFIG_MAX_TOKENS_JUDGE): CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_MAX_TOKENS_JUDGE, str),
        (C.CONFIG_GENERAL, C.CONFIG_BEST_OF_FIGHTER): CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_BEST_OF_FIGHTER, str),
        (C.CONFIG_GENERAL, C.CONFIG_BEST_OF_JUDGE): CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_BEST_OF_JUDGE, str),
        (C.CONFIG_GENERAL, C.CONFIG_MAX_RETRIES): CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_MAX_RETRIES, str),
        (C.CONFIG_GENERAL, C.CONFIG_SAVE_TRANSCRIPTS): CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_SAVE_TRANSCRIPTS, str),
        (C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS): CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, str),
    }
    CONFIG.set(C.CONFIG_GENERAL, C.CONFIG_LLAMA_DEFAULT_MODEL, "qwen3.6:35b")
    CONFIG.set(C.CONFIG_GENERAL, C.CONFIG_OLLAMA_NUM_CTX, "32768")
    CONFIG.set(C.CONFIG_GENERAL, C.CONFIG_OLLAMA_KEEP_ALIVE, "10m")
    CONFIG.set(C.CONFIG_GENERAL, C.CONFIG_MAX_TOKENS_FIGHTER, "64")
    CONFIG.set(C.CONFIG_GENERAL, C.CONFIG_MAX_TOKENS_JUDGE, "128")
    CONFIG.set(C.CONFIG_GENERAL, C.CONFIG_BEST_OF_FIGHTER, "1")
    CONFIG.set(C.CONFIG_GENERAL, C.CONFIG_BEST_OF_JUDGE, "1")
    CONFIG.set(C.CONFIG_GENERAL, C.CONFIG_MAX_RETRIES, "0")
    CONFIG.set(C.CONFIG_GENERAL, C.CONFIG_SAVE_TRANSCRIPTS, "false")
    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, "1")

    payloads = []

    async def fake_post_json(session, payload, retries=0):
        payloads.append(payload)
        schema = payload.get(C.AGENT_FORMAT)
        if not schema:
            return "I make a cautious attack."

        properties = schema.get(C.SCHEMA_PROPERTIES, {})
        if C.NARRATION in properties:
            return json.dumps(
                {
                    C.NARRATION: "Both fighters test range and reset.",
                    C.DELTA: {},
                    C.FIGHT_END: False,
                    C.WINNER: None,
                }
            )
        return json.dumps(
            {
                "judgement_text": "Both attacks are plausible.",
                f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
                f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "0.0",
                f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
                f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
            }
        )

    async def fake_post_json_result(session, payload, retries=0, endpoint=None):
        return ChatResult(content=await fake_post_json(session, payload, retries=retries), metadata={})

    try:
        with (
            patch("llm_fight.agents._post_json_result", new=fake_post_json_result),
            patch.dict(os.environ, {"API_URL": "http://localhost:11434/api/chat"}),
        ):
            result = await sim_module._single_fight()
    finally:
        for (section, key), value in old_values.items():
            CONFIG.set(section, key, value)

    assert result[C.WINNER] == C.DRAW
    assert result[C.LOG_TURN] == "1"
    assert result[C.LOG_P2_FALLBACK_TURNS] == "0"
    assert result[C.LOG_P2_FALLBACK_USED] == "false"
    assert len(payloads) == 4
    assert {payload[C.AGENT_OPTIONS][C.NUM_CTX] for payload in payloads} == {32768}
    assert {payload[C.AGENT_KEEP_ALIVE] for payload in payloads} == {"10m"}

    fighter_payloads = [payload for payload in payloads if C.AGENT_FORMAT not in payload]
    judge_payloads = [payload for payload in payloads if C.AGENT_FORMAT in payload]
    assert len(fighter_payloads) == 2
    assert len(judge_payloads) == 2
    assert all(1 <= payload[C.AGENT_OPTIONS][C.AGENT_NUM_PREDICT] <= 64 for payload in fighter_payloads)
    assert all(1 <= payload[C.AGENT_OPTIONS][C.AGENT_NUM_PREDICT] <= 128 for payload in judge_payloads)


@pytest.mark.asyncio
async def test_turn_logging_respects_setting():
    async def fake_attempt(*args, **kwargs):
        return "attack"

    async def fake_judge_p1(*args, **kwargs):
        return {
            f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "1.0",
            f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
            "judgement_text": "A hits",
            "explanation": "",
        }

    async def fake_judge_p2(*args, **kwargs):
        return {
            "narration": "A wins",
            "delta": {"A": {}, "B": {C.STATUS_CHANGE: _source_value(C.FIGHTER_A, C.STATUS_UNCONSCIOUS)}},
            "fight_end": True,
            "winner": "A",
        }

    original_setting = CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_LOG_COMBAT_TURNS, bool, fallback=False)
    CONFIG.set(C.CONFIG_GENERAL, C.CONFIG_LOG_COMBAT_TURNS, "true")

    with (
        patch.object(sim_module, "get_fighter_attempt", new=AsyncMock(side_effect=fake_attempt)),
        patch.object(sim_module, "judge_phase1", new=AsyncMock(side_effect=fake_judge_p1)),
        patch.object(sim_module, "judge_phase2", new=AsyncMock(side_effect=fake_judge_p2)),
        patch.object(sim_module, "rand", MagicMock(return_value=0.0), create=True),
        patch.object(sim_module.logger, "info") as mock_info,
    ):
        await sim_module._single_fight()

    CONFIG.set(C.CONFIG_GENERAL, C.CONFIG_LOG_COMBAT_TURNS, str(original_setting).lower())

    assert any("Turn 1" in call.args[0] for call in mock_info.call_args_list)


@pytest.mark.asyncio
async def test_phase2_fallback_metadata_is_preserved_on_turn_and_result():
    async def fake_attempt(*args, **kwargs):
        return "attack"

    async def fake_judge_p1(*args, **kwargs):
        return {
            f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "0.0",
            f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
            "judgement_text": "Both attacks miss.",
            "explanation": "",
        }

    async def fake_judge_p2(*args, **kwargs):
        return {
            C.NARRATION: "The exchange is inconclusive; both fighters keep their guard and reset distance.",
            C.DELTA: {},
            C.FIGHT_END: False,
            C.WINNER: None,
            C.METADATA: {
                C.P2_FALLBACK_USED: True,
                C.P2_FALLBACK_REASON: C.P2_FALLBACK_REASON_PARSE_FAILED,
                C.P2_FALLBACK_POLICY: C.P2_FAILURE_POLICY_FAIL_OPEN,
                C.P2_LLM_ERROR: "RuntimeError: bad json",
            },
            C.P2_ENGINE_FALLBACK_MARKER: True,
        }

    original_max_turns = CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, int, fallback=100)
    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, "1")

    try:
        with (
            patch.object(sim_module, "get_fighter_attempt", new=AsyncMock(side_effect=fake_attempt)),
            patch.object(sim_module, "judge_phase1", new=AsyncMock(side_effect=fake_judge_p1)),
            patch.object(sim_module, "judge_phase2", new=AsyncMock(side_effect=fake_judge_p2)),
            patch.object(sim_module, "rand", MagicMock(return_value=1.0), create=True),
        ):
            result, combat_log = await sim_module._single_fight(return_log=True)
    finally:
        CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, str(original_max_turns))

    turn_p2 = combat_log.turns[0].judge_p2
    assert turn_p2[C.DELTA] == {}
    assert turn_p2[C.FIGHT_END] is False
    assert turn_p2[C.WINNER] is None
    assert turn_p2[C.METADATA][C.P2_FALLBACK_USED] is True
    assert C.P2_ENGINE_FALLBACK_MARKER not in turn_p2
    assert result[C.LOG_P2_FALLBACK_TURNS] == "1"
    assert result[C.LOG_P2_FALLBACK_USED] == "true"


@pytest.mark.asyncio
async def test_invalid_failed_attempts_cannot_apply_p2_damage_or_winner():
    fighters = []
    original_from_preset = sim_module.FighterState.from_preset

    def capture_from_preset(id_, preset, config_section=None):
        fighter = original_from_preset(id_, preset, config_section=config_section)
        fighters.append(fighter)
        return fighter

    async def fake_get_attempt(*args, **kwargs):
        return ""

    async def fake_judge_p1(*args, **kwargs):
        return {
            f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": False,
            f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "0.0",
            f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": False,
            f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
            "judgement_text": "Both attempts are empty.",
            "explanation": "No valid actions.",
        }

    async def fake_judge_p2(*args, **kwargs):
        return {
            C.NARRATION: "The judge wrongly invents a decisive wound.",
            C.DELTA: {C.FIGHTER_A: {}, C.FIGHTER_B: {C.STATUS_CHANGE: C.STATUS_UNCONSCIOUS}},
            C.FIGHT_END: True,
            C.WINNER: C.FIGHTER_A,
        }

    original_max_turns = CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, int, fallback=100)
    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, "1")

    with (
        patch.object(sim_module.FighterState, "from_preset", side_effect=capture_from_preset),
        patch.object(sim_module, "get_fighter_attempt", new=AsyncMock(side_effect=fake_get_attempt)),
        patch.object(sim_module, "judge_phase1", new=AsyncMock(side_effect=fake_judge_p1)),
        patch.object(sim_module, "judge_phase2", new=AsyncMock(side_effect=fake_judge_p2)),
        patch.object(sim_module.logger, "warning") as mock_warning,
    ):
        result = await sim_module._single_fight()

    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, str(original_max_turns))

    assert result[C.WINNER] == C.DRAW
    assert fighters[1].status == C.FighterStatus.FIGHTING
    assert any("both attempts were invalid and failed" in call.args[0] for call in mock_warning.call_args_list)


@pytest.mark.asyncio
async def test_valid_attempts_with_failed_rolls_cannot_apply_sourced_p2_damage_or_winner():
    fighters = []
    original_from_preset = sim_module.FighterState.from_preset

    def capture_from_preset(id_, preset, config_section=None):
        fighter = original_from_preset(id_, preset, config_section=config_section)
        fighters.append(fighter)
        return fighter

    async def fake_judge_p1(*args, **kwargs):
        return {
            f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "0.0",
            f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
            "judgement_text": "Both attempts are possible but fail.",
            "explanation": "",
        }

    async def fake_judge_p2(*args, **kwargs):
        return {
            C.NARRATION: "The judge wrongly invents damage after failed rolls.",
            C.DELTA: {
                C.FIGHTER_A: {C.PAIN_INCREASE: _source_value(C.FIGHTER_B, 30)},
                C.FIGHTER_B: {C.STATUS_CHANGE: _source_value(C.FIGHTER_A, C.STATUS_UNCONSCIOUS)},
            },
            C.FIGHT_END: True,
            C.WINNER: C.FIGHTER_A,
            "unsafe_extra": "wing",
        }

    original_max_turns = CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, int, fallback=100)
    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, "1")

    with (
        patch.object(sim_module.FighterState, "from_preset", side_effect=capture_from_preset),
        patch.object(sim_module, "get_fighter_attempt", new=AsyncMock(return_value="attack")),
        patch.object(sim_module, "judge_phase1", new=AsyncMock(side_effect=fake_judge_p1)),
        patch.object(sim_module, "judge_phase2", new=AsyncMock(side_effect=fake_judge_p2)),
        patch.object(sim_module, "rand", MagicMock(return_value=1.0), create=True),
    ):
        result = await sim_module._single_fight()

    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, str(original_max_turns))

    assert result[C.WINNER] == C.DRAW
    assert fighters[0].pain == 0
    assert fighters[1].status == C.FighterStatus.FIGHTING


@pytest.mark.asyncio
async def test_mixed_success_applies_only_authorized_source_consequences():
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
            "judgement_text": "A succeeds while B fails.",
            "explanation": "",
        }

    async def fake_judge_p2(*args, **kwargs):
        return {
            C.NARRATION: "A lands a hit while overextending; B's failed counter should not matter.",
            C.DELTA: {
                C.FIGHTER_A: {
                    C.HEAT_INCREASE: _source_value(C.FIGHTER_A, 3),
                    C.PAIN_INCREASE: _source_value(C.FIGHTER_B, 99),
                },
                C.FIGHTER_B: {
                    C.PAIN_INCREASE: _source_value(C.FIGHTER_A, 7),
                    C.WOUNDS: [
                        {
                            C.SOURCE: C.FIGHTER_B,
                            C.TARGETED_PART: "head",
                            C.VALUE: 100,
                            C.TYPE: C.DamageType.PIERCING,
                        }
                    ],
                },
            },
            C.FIGHT_END: False,
            C.WINNER: None,
        }

    original_max_turns = CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, int, fallback=100)
    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, "1")

    with (
        patch.object(sim_module.FighterState, "from_preset", side_effect=capture_from_preset),
        patch.object(sim_module, "get_fighter_attempt", new=AsyncMock(return_value="attack")),
        patch.object(sim_module, "judge_phase1", new=AsyncMock(side_effect=fake_judge_p1)),
        patch.object(sim_module, "judge_phase2", new=AsyncMock(side_effect=fake_judge_p2)),
        patch.object(sim_module, "rand", MagicMock(return_value=0.0), create=True),
    ):
        result = await sim_module._single_fight()

    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, str(original_max_turns))

    assert result[C.WINNER] == C.DRAW
    assert fighters[0].heat == 3
    assert fighters[0].pain == 0
    assert fighters[1].pain == 7
    assert fighters[1].parts["head"].status == "intact"


@pytest.mark.asyncio
@pytest.mark.parametrize("winner", [C.FIGHTER_A, None])
async def test_judge_only_fight_end_continues_when_state_is_not_terminal(winner):
    async def fake_judge_p1(*args, **kwargs):
        return {
            f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "1.0",
            f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
            "judgement_text": "A succeeds without a terminal effect.",
            "explanation": "",
        }

    async def fake_judge_p2(*args, **kwargs):
        return {
            C.NARRATION: "The judge declares an unsupported ending.",
            C.DELTA: {},
            C.FIGHT_END: True,
            C.WINNER: winner,
        }

    original_max_turns = CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, int, fallback=100)
    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, "2")

    judge_p2 = AsyncMock(side_effect=fake_judge_p2)
    with (
        patch.object(sim_module, "get_fighter_attempt", new=AsyncMock(return_value="attack")),
        patch.object(sim_module, "judge_phase1", new=AsyncMock(side_effect=fake_judge_p1)),
        patch.object(sim_module, "judge_phase2", new=judge_p2),
        patch.object(sim_module, "rand", MagicMock(return_value=0.0), create=True),
        patch.object(sim_module.logger, "warning") as mock_warning,
    ):
        result = await sim_module._single_fight()

    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, str(original_max_turns))

    assert result[C.WINNER] == C.DRAW
    assert judge_p2.await_count == 2
    assert any("Ignoring judge-only outcome" in call.args[0] for call in mock_warning.call_args_list)


@pytest.mark.asyncio
async def test_new_ttl_one_effect_reaches_next_turn_prompts_before_expiring():
    captured_fighter_prompts = []
    captured_p1_states = []
    captured_p2_states = []

    async def fake_get_attempt(fighter, opponent, combat_log=None, turn_window=0, **kwargs):
        captured_fighter_prompts.append(fighter.to_json())
        return "attack"

    async def fake_judge_p1(state, *args, **kwargs):
        captured_p1_states.append(state)
        return {
            f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "1.0",
            f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
            "judgement_text": "A succeeds.",
            "explanation": "",
        }

    p2_turn = 0

    async def fake_judge_p2(p2_input_state, rolls, **kwargs):
        nonlocal p2_turn
        p2_turn += 1
        captured_p2_states.append(p2_input_state)
        if p2_turn == 1:
            return {
                C.NARRATION: "A briefly stuns B.",
                C.DELTA: {
                    C.FIGHTER_B: {
                        C.EFFECTS_ADDED: [
                            {
                                C.SOURCE: C.FIGHTER_A,
                                C.NAME: "stunned",
                                C.VALUE: 1,
                                C.EFFECT_TTL: 1,
                            }
                        ]
                    }
                },
                C.FIGHT_END: False,
                C.WINNER: None,
            }
        return {C.NARRATION: "The stun fades.", C.DELTA: {}, C.FIGHT_END: False, C.WINNER: None}

    original_max_turns = CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, int, fallback=100)
    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, "2")

    try:
        with (
            patch.object(sim_module, "get_fighter_attempt", new=AsyncMock(side_effect=fake_get_attempt)),
            patch.object(sim_module, "judge_phase1", new=AsyncMock(side_effect=fake_judge_p1)),
            patch.object(sim_module, "judge_phase2", new=AsyncMock(side_effect=fake_judge_p2)),
            patch.object(sim_module, "rand", MagicMock(return_value=0.0), create=True),
        ):
            result, log = await sim_module._single_fight(return_log=True)
    finally:
        CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, str(original_max_turns))

    assert result[C.WINNER] == C.DRAW
    turn1_effects = log.turns[0].state_B_after[C.DEBUFFS]
    assert turn1_effects[0][C.NAME] == "stunned"
    assert turn1_effects[0][C.EFFECT_TTL] == 1
    assert "fresh_turns" not in turn1_effects[0]

    turn2_b_fighter_prompt = captured_fighter_prompts[3]
    assert turn2_b_fighter_prompt[C.DEBUFFS][0][C.NAME] == "stunned"
    assert captured_p1_states[1][C.FIGHTER_B][C.DEBUFFS][0][C.NAME] == "stunned"
    assert captured_p2_states[1][f"fighter_{C.FIGHTER_B}"][C.DEBUFFS][0][C.NAME] == "stunned"

    assert log.turns[1].state_B_after[C.DEBUFFS] == []
