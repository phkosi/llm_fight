import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
import csv
import json
import os
import random

import llm_fight.simulation as sim_module
from llm_fight.agents import ChatResult
from llm_fight.judge import JudgePhase2FailureError
from llm_fight.state import Effect, FighterState  # Keep for spec

# from llm_fight.anatomy import PRESETS as ANATOMY_PRESETS # No longer needed for this test's mocking strategy
from llm_fight.engine import constants as C
from llm_fight.config import CONFIG, Config
from llm_fight.profiles import build_fighter_profile


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


def _patch_batch_config(runs: int, concurrency: int, seed_value: int = 42):
    orig_get = sim_module.config_mod.CONFIG.get

    def fake_get(section, key, cast=str, fallback=None):
        if section == C.CONFIG_SIMULATION and key == C.CONFIG_RUNS:
            return runs
        if section == C.CONFIG_SIMULATION and key == C.CONFIG_CONCURRENT_RUNS:
            return concurrency
        if section == C.CONFIG_SIMULATION and key == C.CONFIG_SEED:
            return seed_value
        return orig_get(section, key, cast, fallback)

    return patch.object(sim_module.config_mod.CONFIG, "get", side_effect=fake_get)


@pytest.mark.asyncio
@patch("llm_fight.simulation.get_fighter_attempt", new_callable=AsyncMock)
@patch("llm_fight.simulation.judge_phase1", new_callable=AsyncMock)
@patch("llm_fight.simulation.judge_phase2", new_callable=AsyncMock)
@patch("llm_fight.state.FighterState.from_preset")  # This is the crucial mock for instances inside _single_fight
async def test_single_fight_runs_to_completion(
    mock_from_preset,  # Renamed for clarity, this is the mock for FighterState.from_preset
    mock_judge_p2,
    mock_judge_p1,
    mock_get_fighter_attempt,
):
    original_max_turns = CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, int, fallback=100)
    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, "5")

    # Create MagicMock instances for fighters
    fighter_a_mock = MagicMock(spec=FighterState)
    fighter_a_mock.id = "A"
    fighter_a_mock.status = C.FighterStatus.FIGHTING
    fighter_a_mock.parts = {"head": object(), "torso": object()}
    fighter_a_mock.to_json.return_value = {
        "id": "A",
        C.STATUS: C.FighterStatus.FIGHTING,
        C.PAIN: 0,
    }  # For judge_phase1 context
    fighter_a_mock.apply_delta = MagicMock()  # Ensure it can be called
    fighter_a_mock.apply_effects = MagicMock()  # Ensure it can be called

    fighter_b_mock = MagicMock(spec=FighterState)
    fighter_b_mock.id = "B"
    fighter_b_mock.status = C.FighterStatus.FIGHTING
    fighter_b_mock.parts = {"head": object(), "torso": object()}
    fighter_b_mock.to_json.return_value = {"id": "B", C.STATUS: C.FighterStatus.FIGHTING, C.PAIN: 0}

    # Define side effect for B's apply_delta to change status
    def b_apply_delta_side_effect(delta):
        if delta.get(C.STATUS_CHANGE) == C.FighterStatus.UNCONSCIOUS:
            fighter_b_mock.status = C.FighterStatus.UNCONSCIOUS

    fighter_b_mock.apply_delta.side_effect = b_apply_delta_side_effect
    fighter_b_mock.apply_effects = MagicMock()

    # Set the side_effect for the mocked FighterState.from_preset
    mock_from_preset.side_effect = [fighter_a_mock, fighter_b_mock]

    mock_get_fighter_attempt.return_value = "Some attempt"
    mock_judge_p1.return_value = {
        f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
        f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "1.0",
        f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
        f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
        "judgement_text": "Judgement P1",
        "explanation": "",
    }

    async def p2_side_effect(p2_input_state, rolls):
        # This delta will be passed to fighter_b_mock.apply_delta
        return {
            "narration": "A lands a decisive blow! B is knocked out!",
            "delta": {"A": {}, "B": {C.STATUS_CHANGE: _source_value(C.FIGHTER_A, C.FighterStatus.UNCONSCIOUS)}},
            "fight_end": True,
            "winner": "A",  # Winner is determined by ID string
        }

    mock_judge_p2.side_effect = p2_side_effect

    with patch.object(sim_module, "rand", MagicMock(return_value=0.0), create=True) as mock_rand_obj:
        result = await sim_module._single_fight()

    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, str(original_max_turns))

    assert result[C.WINNER] == "A"
    assert result[C.LOG_TURN] == "1"
    mock_get_fighter_attempt.assert_called()
    mock_judge_p1.assert_called_once()
    assert "recent_log" in mock_judge_p1.call_args.kwargs
    mock_judge_p2.assert_called_once()
    mock_rand_obj.assert_called()

    fighter_b_mock.apply_delta.assert_called_with({C.STATUS_CHANGE: C.FighterStatus.UNCONSCIOUS})
    assert fighter_b_mock.status == C.FighterStatus.UNCONSCIOUS
    assert fighter_a_mock.status == C.FighterStatus.FIGHTING  # A should be unchanged


@pytest.mark.asyncio
async def test_single_fight_uses_fight_rng_for_success_rolls():
    async def fake_get_attempt(*args, **kwargs):
        return "attack"

    async def fake_judge_p1(*args, **kwargs):
        return {
            f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "1.0",
            f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
            "judgement_text": "A succeeds and B fails.",
            "explanation": "",
        }

    async def fake_judge_p2(*args, **kwargs):
        return {
            C.NARRATION: "A wins.",
            C.DELTA: {C.FIGHTER_B: {C.STATUS_CHANGE: _source_value(C.FIGHTER_A, C.STATUS_UNCONSCIOUS)}},
            C.FIGHT_END: True,
            C.WINNER: C.FIGHTER_A,
        }

    fight_rng = MagicMock()
    fight_rng.random.side_effect = [0.0, 0.99]

    with (
        patch.object(sim_module, "get_fighter_attempt", new=AsyncMock(side_effect=fake_get_attempt)),
        patch.object(sim_module, "judge_phase1", new=AsyncMock(side_effect=fake_judge_p1)),
        patch.object(sim_module, "judge_phase2", new=AsyncMock(side_effect=fake_judge_p2)),
        patch.object(sim_module, "rand", side_effect=AssertionError("global rand should not be used")) as mock_rand,
    ):
        result, combat_log = await sim_module._single_fight(fight_rng=fight_rng, return_log=True)

    assert result[C.WINNER] == C.FIGHTER_A
    assert fight_rng.random.call_count == 2
    mock_rand.assert_not_called()
    turn_rolls = combat_log.turns[0].rolls
    assert turn_rolls[C.FIGHTER_A]["roll"] == 0.0
    assert turn_rolls[C.FIGHTER_A]["success"] is True
    assert turn_rolls[C.FIGHTER_A]["reason"] == "success"
    assert turn_rolls[C.FIGHTER_B]["roll"] == 0.99
    assert turn_rolls[C.FIGHTER_B]["success"] is False
    assert turn_rolls[C.FIGHTER_B]["reason"] == "failed"


@pytest.mark.asyncio
async def test_single_fight_uses_configured_custom_anatomy_profiles(tmp_path):
    profile_a = _write_profile(tmp_path / "a_profile.json", _custom_profile("left_wing"))
    profile_b = _write_profile(tmp_path / "b_profile.json", _custom_profile("tentacle_1"))
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
                f"anatomy_profile = {profile_a.name}",
                "",
                "[B]",
                f"profile = {profile_b.name}",
            ]
        ),
        encoding="utf-8",
    )
    p1_states = []
    p2_inputs = []

    async def fake_get_attempt(*args, **kwargs):
        return "attack"

    async def fake_judge_p1(state, *args, **kwargs):
        p1_states.append(state)
        return {
            f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "0.0",
            f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
            "judgement_text": "Both actions miss.",
            "explanation": "",
        }

    async def fake_judge_p2(p2_input, *args, **kwargs):
        p2_inputs.append(p2_input)
        return {
            C.NARRATION: "They circle.",
            C.DELTA: {},
            C.FIGHT_END: False,
            C.WINNER: None,
        }

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
    assert "left_wing" in p1_states[0][C.FIGHTER_A]["parts"]
    assert "tentacle_1" in p1_states[0][C.FIGHTER_B]["parts"]
    assert "left_wing" in p2_inputs[0]["valid_target_parts"][C.FIGHTER_A]
    assert "tentacle_1" in p2_inputs[0]["valid_target_parts"][C.FIGHTER_B]
    assert "left_wing" in combat_log.turns[0].state_A_before["parts"]
    assert "tentacle_1" in combat_log.turns[0].state_B_after["parts"]


def test_fighter_creation_nudges_are_deterministic_with_fight_rng():
    rng_a = random.Random(1234)
    rng_b = random.Random(1234)

    nudges_a = [sim_module.choose_fighter_creation_nudge(rng_a) for _ in range(6)]
    nudges_b = [sim_module.choose_fighter_creation_nudge(rng_b) for _ in range(6)]

    assert nudges_a == nudges_b
    assert set(nudges_a).issubset(set(C.FIGHTER_CREATION_NUDGES))


@pytest.mark.asyncio
async def test_configured_mode_does_not_call_profile_generation(tmp_path):
    config_path = tmp_path / "game.ini"
    config_path.write_text(
        "\n".join(
            [
                "[SIMULATION]",
                "max_turns = 1",
                "",
                "[General]",
                "fighter_creation_mode = configured",
            ]
        ),
        encoding="utf-8",
    )

    async def fake_get_attempt(*args, **kwargs):
        return "attack"

    async def fake_judge_p1(*args, **kwargs):
        return {
            f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "0.0",
            f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
            "judgement_text": "No one lands.",
            "explanation": "",
        }

    async def fake_judge_p2(*args, **kwargs):
        return {C.NARRATION: "They reset.", C.DELTA: {}, C.FIGHT_END: False, C.WINNER: None}

    old_config = sim_module.config_mod.CONFIG
    sim_module.config_mod.CONFIG = Config(config_path)
    try:
        with (
            patch.object(sim_module, "generate_fighter_profile", new=AsyncMock(side_effect=AssertionError)),
            patch.object(sim_module, "get_fighter_attempt", new=AsyncMock(side_effect=fake_get_attempt)),
            patch.object(sim_module, "judge_phase1", new=AsyncMock(side_effect=fake_judge_p1)),
            patch.object(sim_module, "judge_phase2", new=AsyncMock(side_effect=fake_judge_p2)),
        ):
            result = await sim_module._single_fight()
    finally:
        sim_module.config_mod.CONFIG = old_config

    assert result[C.WINNER] == C.DRAW


@pytest.mark.asyncio
async def test_generated_profile_mode_creates_custom_anatomy_before_turn_one(tmp_path):
    config_path = tmp_path / "game.ini"
    config_path.write_text(
        "\n".join(
            [
                "[General]",
                "fighter_creation_mode = generated",
                "fighter_A = A",
                "fighter_B = B",
                "",
                "[SIMULATION]",
                "max_turns = 1",
                "",
                "[A]",
                "class = Config Knight",
                "",
                "[B]",
                "class = Config Assassin",
            ]
        ),
        encoding="utf-8",
    )
    calls = []
    p1_states = []
    p2_inputs = []

    async def fake_generate(fighter_id, section, opponent_section, nudge, *, config=None):
        calls.append((fighter_id, section, opponent_section, nudge))
        part_id = "left_wing" if fighter_id == C.FIGHTER_A else "tentacle_1"
        profile = _custom_profile(part_id)
        profile[C.THEME] = "generated theme"
        return build_fighter_profile(profile)

    async def fake_get_attempt(*args, **kwargs):
        return "attack"

    async def fake_judge_p1(state, *args, **kwargs):
        p1_states.append(state)
        return {
            f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "0.0",
            f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
            "judgement_text": "No one lands.",
            "explanation": "",
        }

    async def fake_judge_p2(p2_input, *args, **kwargs):
        p2_inputs.append(p2_input)
        return {C.NARRATION: "They reset.", C.DELTA: {}, C.FIGHT_END: False, C.WINNER: None}

    old_config = sim_module.config_mod.CONFIG
    sim_module.config_mod.CONFIG = Config(config_path)
    try:
        with (
            patch.object(sim_module, "generate_fighter_profile", new=AsyncMock(side_effect=fake_generate)),
            patch.object(sim_module, "get_fighter_attempt", new=AsyncMock(side_effect=fake_get_attempt)),
            patch.object(sim_module, "judge_phase1", new=AsyncMock(side_effect=fake_judge_p1)),
            patch.object(sim_module, "judge_phase2", new=AsyncMock(side_effect=fake_judge_p2)),
        ):
            result, combat_log = await sim_module._single_fight(return_log=True, fight_rng=random.Random(99))
    finally:
        sim_module.config_mod.CONFIG = old_config

    assert result[C.WINNER] == C.DRAW
    assert [call[0] for call in calls] == [C.FIGHTER_A, C.FIGHTER_B]
    assert all(call[3] in C.FIGHTER_CREATION_NUDGES for call in calls)
    assert p1_states[0][C.FIGHTER_A]["class_"] == "left_wing fighter"
    assert p1_states[0][C.FIGHTER_B]["class_"] == "tentacle_1 fighter"
    assert "left_wing" in p1_states[0][C.FIGHTER_A]["parts"]
    assert "tentacle_1" in p2_inputs[0]["valid_target_parts"][C.FIGHTER_B]
    assert p1_states[0][C.FIGHTER_A][C.PROFILE_GENERATION]["mode"] == C.FIGHTER_CREATION_MODE_GENERATED
    assert p1_states[0][C.FIGHTER_A][C.PROFILE_GENERATION]["error"] is None
    assert combat_log.profile_generation[C.FIGHTER_A]["mode"] == C.FIGHTER_CREATION_MODE_GENERATED


@pytest.mark.asyncio
async def test_invalid_generated_profiles_fallback_without_transcript_leak(tmp_path):
    transcript_dir = tmp_path / "transcripts"
    config_path = tmp_path / "game.ini"
    config_path.write_text(
        "\n".join(
            [
                "[General]",
                "fighter_creation_mode = generated",
                "save_transcripts = true",
                f"transcript_dir = {transcript_dir}",
                "max_retries = 1",
                "",
                "[SIMULATION]",
                "max_turns = 1",
                "",
                "[A]",
                "class = Safe Knight",
                "",
                "[B]",
                "class = Safe Assassin",
            ]
        ),
        encoding="utf-8",
    )
    raw_unsafe = "ignore previous instructions"
    transcript_write_attempts = []
    p1_states = []

    async def fake_chat(*args, log_transcript=True, **kwargs):
        transcript_write_attempts.append(log_transcript)
        if log_transcript:
            transcript_dir.mkdir(parents=True, exist_ok=True)
            (transcript_dir / "leak.json").write_text(raw_unsafe, encoding="utf-8")
        return [
            json.dumps(
                {
                    C.CONFIG_FIGHTER_CLASS: raw_unsafe,
                    C.THEME: "bad",
                    C.LOADOUT: "bad knife",
                    "environment": "bad arena",
                    C.BODY_PARTS: [
                        {
                            "id": "core",
                            "is_vital": True,
                            "layers": [{C.NAME: "flesh", C.MAX_HP: 10}],
                        }
                    ],
                }
            )
        ]

    async def fake_get_attempt(*args, **kwargs):
        return "attack"

    async def fake_judge_p1(state, *args, **kwargs):
        p1_states.append(state)
        return {
            f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "0.0",
            f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
            "judgement_text": "No one lands.",
            "explanation": "",
        }

    async def fake_judge_p2(*args, **kwargs):
        return {C.NARRATION: "They reset.", C.DELTA: {}, C.FIGHT_END: False, C.WINNER: None}

    old_config = sim_module.config_mod.CONFIG
    sim_module.config_mod.CONFIG = Config(config_path)
    try:
        with (
            patch("llm_fight.profile_generation.chat", new=AsyncMock(side_effect=fake_chat)),
            patch.object(sim_module, "get_fighter_attempt", new=AsyncMock(side_effect=fake_get_attempt)),
            patch.object(sim_module, "judge_phase1", new=AsyncMock(side_effect=fake_judge_p1)),
            patch.object(sim_module, "judge_phase2", new=AsyncMock(side_effect=fake_judge_p2)),
        ):
            result, combat_log = await sim_module._single_fight(return_log=True, fight_rng=random.Random(7))
    finally:
        sim_module.config_mod.CONFIG = old_config

    assert result[C.WINNER] == C.DRAW
    assert transcript_write_attempts
    assert all(flag is False for flag in transcript_write_attempts)
    assert not transcript_dir.exists()
    serialized_state = json.dumps(p1_states[0], default=str)
    assert raw_unsafe not in serialized_state
    assert p1_states[0][C.FIGHTER_A]["class_"] == "Safe Knight"
    assert p1_states[0][C.FIGHTER_A][C.PROFILE_GENERATION] == {
        "mode": "fallback",
        "nudge": p1_states[0][C.FIGHTER_A][C.PROFILE_GENERATION]["nudge"],
        "error": C.PROFILE_GENERATION_ERROR_INVALID,
    }
    assert combat_log.profile_generation[C.FIGHTER_A]["error"] == C.PROFILE_GENERATION_ERROR_INVALID


@pytest.mark.asyncio
async def test_single_fight_emits_play_events_and_token_metadata():
    events = []

    async def fake_get_attempt(*args, **kwargs):
        kwargs["on_metadata"]({"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3})
        return "attack"

    async def fake_judge_p1(*args, **kwargs):
        kwargs["on_metadata"]({"prompt_tokens": 4, "completion_tokens": 5, "total_tokens": 9})
        return {
            f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "0.0",
            f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
            "judgement_text": "No one lands.",
            "explanation": "",
        }

    async def fake_judge_p2(*args, **kwargs):
        kwargs["on_metadata"]({"prompt_tokens": 6, "completion_tokens": 7, "total_tokens": 13})
        return {C.NARRATION: "They reset.", C.DELTA: {}, C.FIGHT_END: False, C.WINNER: None}

    original_max_turns = CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, int, fallback=100)
    CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, "1")
    try:
        with (
            patch.object(sim_module, "get_fighter_attempt", new=AsyncMock(side_effect=fake_get_attempt)),
            patch.object(sim_module, "judge_phase1", new=AsyncMock(side_effect=fake_judge_p1)),
            patch.object(sim_module, "judge_phase2", new=AsyncMock(side_effect=fake_judge_p2)),
        ):
            result, combat_log = await sim_module._single_fight(return_log=True, on_event=events.append)
    finally:
        CONFIG.set(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, str(original_max_turns))

    names = [event.name for event in events]
    assert result[C.WINNER] == C.DRAW
    assert combat_log.turns[0].turn == 1
    assert names.index(C.FIGHT_EVENT_FIGHTERS_READY) < names.index(C.FIGHT_EVENT_FIGHTER_ACTION_START)
    assert names.index(C.FIGHT_EVENT_JUDGE_PHASE1_START) < names.index(C.FIGHT_EVENT_JUDGE_PHASE1_END)
    assert names.index(C.FIGHT_EVENT_ROLLS_START) < names.index(C.FIGHT_EVENT_ROLLS_END)
    assert names.index(C.FIGHT_EVENT_JUDGE_PHASE2_START) < names.index(C.FIGHT_EVENT_JUDGE_PHASE2_END)
    assert names.index(C.FIGHT_EVENT_TURN_COMPLETE) < names.index(C.FIGHT_EVENT_FIGHT_COMPLETE)
    token_events = [event for event in events if event.name == C.FIGHT_EVENT_TOKEN_METADATA]
    assert {event.data["phase"] for event in token_events} == {"fighter_action", "judge_phase1", "judge_phase2"}
    assert len(token_events) == 4
    assert sum(event.data["metadata"]["total_tokens"] for event in token_events) == 28


@pytest.mark.asyncio
async def test_generated_profile_events_precede_fighters_ready(tmp_path):
    config_path = tmp_path / "game.ini"
    config_path.write_text(
        "\n".join(
            [
                "[General]",
                "fighter_creation_mode = generated",
                "",
                "[SIMULATION]",
                "max_turns = 1",
            ]
        ),
        encoding="utf-8",
    )
    events = []

    async def fake_generate(fighter_id, section, opponent_section, nudge, **kwargs):
        return build_fighter_profile(_custom_profile(f"creative_{fighter_id.lower()}"))

    async def fake_get_attempt(*args, **kwargs):
        return "attack"

    async def fake_judge_p1(*args, **kwargs):
        return {
            f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "0.0",
            f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
            "judgement_text": "No one lands.",
            "explanation": "",
        }

    async def fake_judge_p2(*args, **kwargs):
        return {C.NARRATION: "They reset.", C.DELTA: {}, C.FIGHT_END: False, C.WINNER: None}

    old_config = sim_module.config_mod.CONFIG
    sim_module.config_mod.CONFIG = Config(config_path)
    try:
        with (
            patch.object(sim_module, "generate_fighter_profile", new=AsyncMock(side_effect=fake_generate)),
            patch.object(sim_module, "get_fighter_attempt", new=AsyncMock(side_effect=fake_get_attempt)),
            patch.object(sim_module, "judge_phase1", new=AsyncMock(side_effect=fake_judge_p1)),
            patch.object(sim_module, "judge_phase2", new=AsyncMock(side_effect=fake_judge_p2)),
        ):
            await sim_module._single_fight(return_log=True, on_event=events.append, fight_rng=random.Random(3))
    finally:
        sim_module.config_mod.CONFIG = old_config

    names = [event.name for event in events]
    assert names.index(C.FIGHT_EVENT_PROFILE_GENERATION_START) < names.index(C.FIGHT_EVENT_FIGHTERS_READY)
    assert names.count(C.FIGHT_EVENT_PROFILE_GENERATION_START) == 2
    assert names.count(C.FIGHT_EVENT_PROFILE_GENERATION_END) == 2


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
async def test_run_batch_concurrency(tmp_path):

    running = 0
    max_running = 0
    lock = asyncio.Lock()

    async def fake_fight(*args, **kwargs):
        nonlocal running, max_running
        async with lock:
            running += 1
            if running > max_running:
                max_running = running
        await asyncio.sleep(0.01)
        async with lock:
            running -= 1
        return {C.WINNER: "A", C.LOG_TURN: "1"}

    with patch.object(sim_module, "_single_fight", side_effect=fake_fight):
        orig_get = sim_module.config_mod.CONFIG.get

        def fake_get(section, key, cast=str, fallback=None):
            if section == C.CONFIG_SIMULATION and key == C.CONFIG_RUNS:
                return 4
            if section == C.CONFIG_SIMULATION and key == C.CONFIG_CONCURRENT_RUNS:
                return 2
            return orig_get(section, key, cast, fallback)

        with patch.object(sim_module.config_mod.CONFIG, "get", side_effect=fake_get):
            out_file = tmp_path / "result.csv"
            ret = await sim_module.run_batch(out_file)

    assert max_running == 2
    assert ret == out_file
    assert out_file.exists()


@pytest.mark.asyncio
async def test_run_batch_exact_runs(tmp_path):
    calls = 0

    async def fake_fight(*args, **kwargs):
        nonlocal calls
        calls += 1
        return {C.WINNER: "A", C.LOG_TURN: "1"}

    with patch.object(sim_module, "_single_fight", side_effect=fake_fight):
        orig_get = sim_module.config_mod.CONFIG.get

        def fake_get(section, key, cast=str, fallback=None):
            if section == C.CONFIG_SIMULATION and key == C.CONFIG_RUNS:
                return 3
            if section == C.CONFIG_SIMULATION and key == C.CONFIG_CONCURRENT_RUNS:
                return 1
            return orig_get(section, key, cast, fallback)

        with patch.object(sim_module.config_mod.CONFIG, "get", side_effect=fake_get):
            await sim_module.run_batch(tmp_path / "result.csv")

    assert calls == 3


@pytest.mark.asyncio
async def test_run_batch_progress_callback(tmp_path):
    async def fake_fight(*args, **kwargs):
        await asyncio.sleep(0)
        return {C.WINNER: "A", C.LOG_TURN: "1"}

    progress_calls = []

    with patch.object(sim_module, "_single_fight", side_effect=fake_fight):
        orig_get = sim_module.config_mod.CONFIG.get

        def fake_get(section, key, cast=str, fallback=None):
            if section == C.CONFIG_SIMULATION and key == C.CONFIG_RUNS:
                return 2
            if section == C.CONFIG_SIMULATION and key == C.CONFIG_CONCURRENT_RUNS:
                return 1
            return orig_get(section, key, cast, fallback)

        with patch.object(sim_module.config_mod.CONFIG, "get", side_effect=fake_get):
            out_file = tmp_path / "prog.csv"

            def cb(done, total):
                progress_calls.append((done, total))

            await sim_module.run_batch(out_file, progress=cb)

    assert progress_calls == [(1, 2), (2, 2)]


@pytest.mark.asyncio
async def test_run_batch_flushes_each_completed_result(tmp_path):
    calls = 0
    first_progress_rows = []

    async def fake_fight(*args, **kwargs):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return {C.WINNER: "A" if calls == 1 else "B", C.LOG_TURN: str(calls)}

    out_file = tmp_path / "incremental.csv"

    def progress(done, total):
        if done == 1:
            with open(out_file, newline="") as fp:
                first_progress_rows.extend(csv.DictReader(fp))

    with patch.object(sim_module, "_single_fight", side_effect=fake_fight):
        orig_get = sim_module.config_mod.CONFIG.get

        def fake_get(section, key, cast=str, fallback=None):
            if section == C.CONFIG_SIMULATION and key == C.CONFIG_RUNS:
                return 2
            if section == C.CONFIG_SIMULATION and key == C.CONFIG_CONCURRENT_RUNS:
                return 1
            return orig_get(section, key, cast, fallback)

        with patch.object(sim_module.config_mod.CONFIG, "get", side_effect=fake_get):
            path = await sim_module.run_batch(out_file, progress=progress)

    assert path == out_file
    assert first_progress_rows == [
        {
            C.WINNER: "A",
            C.LOG_TURN: "1",
            C.LOG_P2_FALLBACK_TURNS: "0",
            C.LOG_P2_FALLBACK_USED: "false",
        }
    ]

    with open(out_file, newline="") as fp:
        final_rows = list(csv.DictReader(fp))
    assert final_rows == [
        {
            C.WINNER: "A",
            C.LOG_TURN: "1",
            C.LOG_P2_FALLBACK_TURNS: "0",
            C.LOG_P2_FALLBACK_USED: "false",
        },
        {
            C.WINNER: "B",
            C.LOG_TURN: "2",
            C.LOG_P2_FALLBACK_TURNS: "0",
            C.LOG_P2_FALLBACK_USED: "false",
        },
    ]


@pytest.mark.asyncio
async def test_run_batch_writes_rows_in_run_index_order_with_out_of_order_completion(tmp_path):
    call_index = 0
    delays = [0.03, 0, 0.01]
    progress_calls = []
    first_progress_rows = []
    out_file = tmp_path / "ordered.csv"

    async def fake_fight(*args, fight_rng=None, **kwargs):
        nonlocal call_index
        run_index = call_index
        call_index += 1
        await asyncio.sleep(delays[run_index])
        return {C.WINNER: str(run_index), C.LOG_TURN: str(run_index + 1)}

    def progress(done, total):
        progress_calls.append((done, total))
        if done == 1:
            with open(out_file, newline="") as fp:
                first_progress_rows.extend(csv.DictReader(fp))

    with (
        patch.object(sim_module, "_single_fight", side_effect=fake_fight),
        _patch_batch_config(runs=3, concurrency=3, seed_value=99),
    ):
        path = await sim_module.run_batch(out_file, progress=progress)

    assert path == out_file
    assert first_progress_rows == []
    assert progress_calls == [(1, 3), (2, 3), (3, 3)]
    with open(out_file, newline="") as fp:
        rows = list(csv.DictReader(fp))
    assert rows == [
        {
            C.WINNER: "0",
            C.LOG_TURN: "1",
            C.LOG_P2_FALLBACK_TURNS: "0",
            C.LOG_P2_FALLBACK_USED: "false",
        },
        {
            C.WINNER: "1",
            C.LOG_TURN: "2",
            C.LOG_P2_FALLBACK_TURNS: "0",
            C.LOG_P2_FALLBACK_USED: "false",
        },
        {
            C.WINNER: "2",
            C.LOG_TURN: "3",
            C.LOG_P2_FALLBACK_TURNS: "0",
            C.LOG_P2_FALLBACK_USED: "false",
        },
    ]


async def _run_seeded_fake_batch(tmp_path, seed_value, delays, filename):
    call_index = 0

    async def fake_fight(*args, fight_rng=None, **kwargs):
        nonlocal call_index
        run_index = call_index
        call_index += 1
        first = fight_rng.random()
        second = fight_rng.random()
        await asyncio.sleep(delays[run_index])
        return {
            C.WINNER: C.FIGHTER_A if first < 0.5 else C.FIGHTER_B,
            C.LOG_TURN: str(int(second * 1000)),
        }

    out_file = tmp_path / filename
    with (
        patch.object(sim_module, "_single_fight", side_effect=fake_fight),
        _patch_batch_config(runs=len(delays), concurrency=len(delays), seed_value=seed_value),
    ):
        await sim_module.run_batch(out_file)

    with open(out_file, newline="") as fp:
        return list(csv.DictReader(fp))


@pytest.mark.asyncio
async def test_run_batch_is_deterministic_across_varied_completion_order(tmp_path):
    delays_a = [0.03, 0, 0.01, 0.02]
    delays_b = [0, 0.03, 0.02, 0.01]

    rows_a = await _run_seeded_fake_batch(tmp_path, 1234, delays_a, "seeded_a.csv")
    rows_b = await _run_seeded_fake_batch(tmp_path, 1234, delays_b, "seeded_b.csv")

    assert rows_a == rows_b


@pytest.mark.asyncio
async def test_run_batch_base_seed_changes_per_fight_rng_streams(tmp_path):
    delays = [0, 0, 0, 0]

    rows_a = await _run_seeded_fake_batch(tmp_path, 1234, delays, "seeded_a.csv")
    rows_b = await _run_seeded_fake_batch(tmp_path, 4321, delays, "seeded_b.csv")

    assert rows_a != rows_b


@pytest.mark.asyncio
async def test_run_batch_handles_errors(tmp_path):
    async def failing_fight(*args, **kwargs):
        raise RuntimeError("boom")

    with patch.object(sim_module, "_single_fight", side_effect=failing_fight):
        orig_get = sim_module.config_mod.CONFIG.get

        def fake_get(section, key, cast=str, fallback=None):
            if section == C.CONFIG_SIMULATION and key == C.CONFIG_RUNS:
                return 2
            if section == C.CONFIG_SIMULATION and key == C.CONFIG_CONCURRENT_RUNS:
                return 1
            return orig_get(section, key, cast, fallback)

        with (
            patch.object(sim_module.config_mod.CONFIG, "get", side_effect=fake_get),
            patch.object(sim_module.logger, "exception") as mock_exc,
        ):
            out_file = tmp_path / "err.csv"
            path = await sim_module.run_batch(out_file)

    assert path == out_file
    with open(out_file, newline="") as fp:
        rows = list(csv.DictReader(fp))

    assert len(rows) == 2
    assert all(row[C.WINNER] == "error" for row in rows)
    assert mock_exc.call_count == 2


@pytest.mark.asyncio
async def test_run_batch_zero_runs(tmp_path):
    out_file = tmp_path / "empty.csv"

    with patch.object(sim_module, "_single_fight", side_effect=RuntimeError("should not run")) as mock_fight:
        orig_get = sim_module.config_mod.CONFIG.get

        def fake_get(section, key, cast=str, fallback=None):
            if section == C.CONFIG_SIMULATION and key == C.CONFIG_RUNS:
                return 0
            if section == C.CONFIG_SIMULATION and key == C.CONFIG_CONCURRENT_RUNS:
                return 1
            return orig_get(section, key, cast, fallback)

        with patch.object(sim_module.config_mod.CONFIG, "get", side_effect=fake_get):
            path = await sim_module.run_batch(out_file)

    assert path == out_file
    assert out_file.exists()
    with open(out_file, newline="") as fp:
        reader = csv.DictReader(fp)
        rows = list(reader)

    assert reader.fieldnames == [
        C.WINNER,
        C.LOG_TURN,
        C.LOG_P2_FALLBACK_TURNS,
        C.LOG_P2_FALLBACK_USED,
    ]
    assert rows == []
    mock_fight.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrency", [0, -1])
async def test_run_batch_invalid_concurrency_raises_without_starting_fight(tmp_path, concurrency):
    out_file = tmp_path / "invalid_concurrency.csv"
    mock_fight = AsyncMock(return_value={C.WINNER: "A", C.LOG_TURN: "1"})
    orig_get = sim_module.config_mod.CONFIG.get

    def fake_get(section, key, cast=str, fallback=None):
        if section == C.CONFIG_SIMULATION and key == C.CONFIG_RUNS:
            return 1
        if section == C.CONFIG_SIMULATION and key == C.CONFIG_CONCURRENT_RUNS:
            return concurrency
        return orig_get(section, key, cast, fallback)

    with (
        patch.object(sim_module, "_single_fight", new=mock_fight),
        patch.object(sim_module.config_mod.CONFIG, "get", side_effect=fake_get),
    ):
        with pytest.raises(ValueError, match="concurrent_runs"):
            await asyncio.wait_for(sim_module.run_batch(out_file), timeout=0.1)

    assert not out_file.exists()
    mock_fight.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_batch_negative_runs_raises_without_starting_fight(tmp_path):
    out_file = tmp_path / "negative_runs.csv"
    mock_fight = AsyncMock(return_value={C.WINNER: "A", C.LOG_TURN: "1"})
    orig_get = sim_module.config_mod.CONFIG.get

    def fake_get(section, key, cast=str, fallback=None):
        if section == C.CONFIG_SIMULATION and key == C.CONFIG_RUNS:
            return -1
        if section == C.CONFIG_SIMULATION and key == C.CONFIG_CONCURRENT_RUNS:
            return 1
        return orig_get(section, key, cast, fallback)

    with (
        patch.object(sim_module, "_single_fight", new=mock_fight),
        patch.object(sim_module.config_mod.CONFIG, "get", side_effect=fake_get),
    ):
        with pytest.raises(ValueError, match="runs"):
            await asyncio.wait_for(sim_module.run_batch(out_file), timeout=0.1)

    assert not out_file.exists()
    mock_fight.assert_not_awaited()


def test_summarize_batch_csv_counts_error_rows(tmp_path):
    out_file = tmp_path / "summary.csv"
    with out_file.open("w", newline="") as fp:
        writer = csv.DictWriter(
            fp,
            fieldnames=[
                C.WINNER,
                C.LOG_TURN,
                C.LOG_P2_FALLBACK_TURNS,
                C.LOG_P2_FALLBACK_USED,
            ],
        )
        writer.writeheader()
        writer.writerows(
            [
                {
                    C.WINNER: "A",
                    C.LOG_TURN: "1",
                    C.LOG_P2_FALLBACK_TURNS: "2",
                    C.LOG_P2_FALLBACK_USED: "true",
                },
                {
                    C.WINNER: C.BATCH_ERROR_WINNER,
                    C.LOG_TURN: "0",
                    C.LOG_P2_FALLBACK_TURNS: "0",
                    C.LOG_P2_FALLBACK_USED: "false",
                },
            ]
        )

    summary = sim_module.summarize_batch_csv(out_file, total_runs=3)

    assert summary.path == out_file
    assert summary.total_runs == 3
    assert summary.total_rows == 2
    assert summary.completed_rows == 1
    assert summary.error_rows == 1
    assert summary.fallback_rows == 1
    assert summary.fallback_turns == 2
    assert summary.has_errors


@pytest.mark.asyncio
async def test_run_batch_writes_fallback_columns_and_summary_counts(tmp_path):
    async def fake_fight(*args, **kwargs):
        return {
            C.WINNER: C.DRAW,
            C.LOG_TURN: "3",
            C.LOG_P2_FALLBACK_TURNS: "1",
            C.LOG_P2_FALLBACK_USED: "true",
        }

    out_file = tmp_path / "fallback.csv"
    with (
        patch.object(sim_module, "_single_fight", side_effect=fake_fight),
        _patch_batch_config(runs=1, concurrency=1),
    ):
        path = await sim_module.run_batch(out_file)

    with open(path, newline="") as fp:
        rows = list(csv.DictReader(fp))

    assert rows == [
        {
            C.WINNER: C.DRAW,
            C.LOG_TURN: "3",
            C.LOG_P2_FALLBACK_TURNS: "1",
            C.LOG_P2_FALLBACK_USED: "true",
        }
    ]
    summary = sim_module.summarize_batch_csv(path)
    assert summary.error_rows == 0
    assert summary.fallback_rows == 1
    assert summary.fallback_turns == 1


@pytest.mark.asyncio
async def test_run_batch_fail_closed_p2_exception_writes_error_row(tmp_path):
    async def failing_fight(*args, **kwargs):
        raise JudgePhase2FailureError("Judge Phase 2 failed after retries under fail_closed policy")

    out_file = tmp_path / "fail_closed.csv"
    with (
        patch.object(sim_module, "_single_fight", side_effect=failing_fight),
        _patch_batch_config(runs=1, concurrency=1),
        patch.object(sim_module.logger, "exception"),
    ):
        path = await sim_module.run_batch(out_file)

    with open(path, newline="") as fp:
        rows = list(csv.DictReader(fp))

    assert rows == [
        {
            C.WINNER: C.BATCH_ERROR_WINNER,
            C.LOG_TURN: "0",
            C.LOG_P2_FALLBACK_TURNS: "0",
            C.LOG_P2_FALLBACK_USED: "false",
        }
    ]


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

    async def fake_get_attempt(fighter, opponent, combat_log=None, turn_window=0):
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

    async def fake_judge_p2(p2_input_state, rolls):
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
