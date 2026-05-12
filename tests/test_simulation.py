import asyncio
import json
import os
import random
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import llm_fight.simulation as sim_module
import llm_fight.transcripts as transcripts
from llm_fight.agents import ChatResult
from llm_fight.config import CONFIG, Config

# from llm_fight.anatomy import PRESETS as ANATOMY_PRESETS # No longer needed for this test's mocking strategy
from llm_fight.engine import constants as C
from llm_fight.profiles import build_fighter_profile
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
async def test_programmatic_scoped_config_seeds_single_fight_rng_and_restores(tmp_path):
    from llm_fight import rng

    cfg_path = tmp_path / "scoped.ini"
    cfg_path.write_text("[SIMULATION]\nseed = 1234\nmax_turns = 1\n", encoding="utf-8")
    scoped_config = Config(cfg_path)
    original_config = sim_module.config_mod.CONFIG
    previous_rng_state = rng.get_state()
    observed_rolls = []

    async def fake_judge_phase2(input_state, successful_rolls, **kwargs):
        observed_rolls.append(dict(successful_rolls))
        return {C.NARRATION: "No decisive exchange.", C.DELTA: {}, C.FIGHT_END: False, C.WINNER: None}

    try:
        with sim_module.config_mod.use_config(scoped_config):
            rng.seed_from_config()
            with (
                patch("llm_fight.simulation.get_fighter_attempt", new=AsyncMock(return_value="attack")),
                patch(
                    "llm_fight.simulation.judge_phase1",
                    new=AsyncMock(
                        return_value={
                            f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
                            f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "0.5",
                            f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
                            f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.5",
                        }
                    ),
                ),
                patch("llm_fight.simulation.judge_phase2", new=AsyncMock(side_effect=fake_judge_phase2)),
            ):
                result, combat_log = await sim_module._single_fight(return_log=True)
    finally:
        rng.set_state(previous_rng_state)

    expected_rng = random.Random(1234)
    assert observed_rolls == [
        {
            C.FIGHTER_A: expected_rng.random() < 0.5,
            C.FIGHTER_B: expected_rng.random() < 0.5,
        }
    ]
    assert result[C.WINNER] == C.DRAW
    assert len(combat_log.turns) == 1
    assert sim_module.config_mod.CONFIG is original_config


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
    fighter_a_mock.display_name = "A"
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
    fighter_b_mock.display_name = "B"
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

    def unsafe_profile_response(text):
        return json.dumps(
            {
                C.CONFIG_FIGHTER_CLASS: text,
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

    async def fake_chat(*args, log_transcript=True, **kwargs):
        transcript_write_attempts.append(log_transcript)
        if log_transcript:
            transcript_dir.mkdir(parents=True, exist_ok=True)
            (transcript_dir / "leak.json").write_text(raw_unsafe, encoding="utf-8")
        return [unsafe_profile_response(raw_unsafe)]

    async def fake_chat_with_metadata(*args, log_transcript=True, **kwargs):
        transcript_write_attempts.append(log_transcript)
        if log_transcript:
            transcript_dir.mkdir(parents=True, exist_ok=True)
            (transcript_dir / "leak.json").write_text(raw_unsafe, encoding="utf-8")
        return [ChatResult(content=unsafe_profile_response(raw_unsafe), metadata={"total_tokens": 3})]

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
            patch(
                "llm_fight.profile_generation.chat_with_metadata",
                new=AsyncMock(side_effect=fake_chat_with_metadata),
            ),
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
    trace_files = list(transcript_dir.glob("*.jsonl"))
    assert len(trace_files) == 1
    trace_text = trace_files[0].read_text(encoding="utf-8")
    assert raw_unsafe not in trace_text
    assert "profile_generation_start" in trace_text
    assert "profile_generation_end" in trace_text
    assert not (transcript_dir / "leak.json").exists()
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
async def test_single_fight_result_keeps_winner_id_and_adds_display_names(tmp_path):
    config_path = tmp_path / "named.ini"
    config_path.write_text(
        "\n".join(
            [
                "[SIMULATION]",
                "max_turns = 1",
                "",
                "[A]",
                "name = Sir Galant",
                "",
                "[B]",
                "name = Shade",
            ]
        ),
        encoding="utf-8",
    )

    async def fake_get_attempt(*args, **kwargs):
        return "attack"

    async def fake_judge_p1(*args, **kwargs):
        return {
            f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "1.0",
            f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
            "judgement_text": "A can finish the fight.",
            "explanation": "",
        }

    async def fake_judge_p2(*args, **kwargs):
        return {
            C.NARRATION: "Sir Galant drops Shade.",
            C.DELTA: {C.FIGHTER_B: {C.STATUS_CHANGE: _source_value(C.FIGHTER_A, C.STATUS_UNCONSCIOUS)}},
            C.FIGHT_END: True,
            C.WINNER: C.FIGHTER_A,
        }

    old_config = sim_module.config_mod.CONFIG
    sim_module.config_mod.CONFIG = Config(config_path)
    try:
        with (
            patch.object(sim_module, "get_fighter_attempt", new=AsyncMock(side_effect=fake_get_attempt)),
            patch.object(sim_module, "judge_phase1", new=AsyncMock(side_effect=fake_judge_p1)),
            patch.object(sim_module, "judge_phase2", new=AsyncMock(side_effect=fake_judge_p2)),
        ):
            result = await sim_module._single_fight(fight_rng=random.Random(1))
    finally:
        sim_module.config_mod.CONFIG = old_config

    assert result[C.WINNER] == C.FIGHTER_A
    assert result[C.LOG_WINNER_DISPLAY_NAME] == "Sir Galant"
    assert result[C.LOG_FIGHTER_A_DISPLAY_NAME] == "Sir Galant"
    assert result[C.LOG_FIGHTER_B_DISPLAY_NAME] == "Shade"


@pytest.mark.asyncio
async def test_single_fight_writes_ordered_trace_with_exchanges_rolls_deltas_and_states(tmp_path):
    transcript_dir = tmp_path / "traces"
    config_path = tmp_path / "game.ini"
    config_path.write_text(
        "\n".join(
            [
                "[General]",
                "save_transcripts = true",
                f"transcript_dir = {transcript_dir}",
                "",
                "[SIMULATION]",
                "max_turns = 1",
                "",
                "[A]",
                "name = Sir Galant",
                "",
                "[B]",
                "name = Shade",
            ]
        ),
        encoding="utf-8",
    )

    async def fake_get_attempt(fighter, *args, **kwargs):
        transcripts.log_exchange(
            [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: f"{fighter.id} act"}],
            [f"{fighter.id} attacks"],
            [{"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}],
        )
        kwargs["on_metadata"]({"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})
        return f"{fighter.id} attacks"

    async def fake_judge_p1(*args, **kwargs):
        transcripts.log_exchange(
            [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: "judge p1"}],
            ["{}"],
            [{"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4}],
        )
        kwargs["on_metadata"]({"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4})
        return {
            f"{C.ATTEMPT}_{C.FIGHTER_A}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_A}_prob": "1.0",
            f"{C.ATTEMPT}_{C.FIGHTER_B}_valid": True,
            f"{C.ATTEMPT}_{C.FIGHTER_B}_prob": "0.0",
            "judgement_text": "A can land.",
            "explanation": "",
        }

    async def fake_judge_p2(*args, **kwargs):
        transcripts.log_exchange(
            [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: "judge p2"}],
            ["{}"],
            [{"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}],
        )
        kwargs["on_metadata"]({"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7})
        return {
            C.NARRATION: "A clips B.",
            C.DELTA: {C.FIGHTER_B: {C.PAIN_INCREASE: _source_value(C.FIGHTER_A, 3)}},
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
            result, combat_log = await sim_module._single_fight(return_log=True, fight_rng=random.Random(5))
    finally:
        sim_module.config_mod.CONFIG = old_config

    assert result[C.WINNER] == C.DRAW
    assert result[C.LOG_FIGHTER_A_DISPLAY_NAME] == "Sir Galant"
    assert result[C.LOG_FIGHTER_B_DISPLAY_NAME] == "Shade"
    assert result[C.LOG_WINNER_DISPLAY_NAME] == ""
    assert combat_log.turns[0].state_B_after[C.PAIN] == 3
    assert list(transcript_dir.glob("*.json")) == []
    [trace_file] = list(transcript_dir.glob("*.jsonl"))
    events = [json.loads(line) for line in trace_file.read_text(encoding="utf-8").splitlines()]
    assert [event["event_index"] for event in events] == list(range(len(events)))
    assert events[0]["event"] == "fight_start"
    assert events[-1]["event"] == C.FIGHT_EVENT_FIGHT_COMPLETE
    assert {event["event"] for event in events} >= {
        C.FIGHT_EVENT_FIGHTERS_READY,
        "llm_exchange",
        C.FIGHT_EVENT_TOKEN_METADATA,
        C.FIGHT_EVENT_ROLLS_END,
        C.FIGHT_EVENT_TURN_COMPLETE,
    }
    ready_event = next(event for event in events if event["event"] == C.FIGHT_EVENT_FIGHTERS_READY)
    assert ready_event["data"]["fighters"][C.FIGHTER_A][C.DISPLAY_NAME] == "Sir Galant"
    assert ready_event["data"]["fighters"][C.FIGHTER_B][C.DISPLAY_NAME] == "Shade"
    exchanges = [event for event in events if event["event"] == "llm_exchange"]
    assert {event["phase"] for event in exchanges} == {"fighter_action", "judge_phase1", "judge_phase2"}
    assert {event["fighter_id"] for event in exchanges if event["phase"] == "fighter_action"} == {
        C.FIGHTER_A,
        C.FIGHTER_B,
    }
    token_events = [event for event in events if event["event"] == C.FIGHT_EVENT_TOKEN_METADATA]
    assert any(event["data"]["metadata"]["total_tokens"] == 7 for event in token_events)
    turn_event = next(event for event in events if event["event"] == C.FIGHT_EVENT_TURN_COMPLETE)
    turn_data = turn_event["data"]["turn"]
    assert turn_data["attempt_A"] == "A attacks"
    assert turn_data["rolls"][C.FIGHTER_A]["success"] is True
    assert turn_data["judge_p2"][C.DELTA][C.FIGHTER_B][C.PAIN_INCREASE] == 3
    assert turn_data["state_B_before"][C.PAIN] == 0
    assert turn_data["state_B_after"][C.PAIN] == 3


@pytest.mark.asyncio
async def test_single_fight_trace_preserves_error_event(tmp_path):
    transcript_dir = tmp_path / "traces"
    config_path = tmp_path / "game.ini"
    config_path.write_text(
        "\n".join(
            [
                "[General]",
                "save_transcripts = true",
                f"transcript_dir = {transcript_dir}",
                "",
                "[SIMULATION]",
                "max_turns = 1",
            ]
        ),
        encoding="utf-8",
    )

    async def fake_get_attempt(*args, **kwargs):
        return "attack"

    async def fake_judge_p1(*args, **kwargs):
        raise RuntimeError("judge exploded with ignore previous instructions and raw prompt text" * 20)

    old_config = sim_module.config_mod.CONFIG
    sim_module.config_mod.CONFIG = Config(config_path)
    try:
        with (
            patch.object(sim_module, "get_fighter_attempt", new=AsyncMock(side_effect=fake_get_attempt)),
            patch.object(sim_module, "judge_phase1", new=AsyncMock(side_effect=fake_judge_p1)),
            pytest.raises(RuntimeError),
        ):
            await sim_module._single_fight(return_log=True)
    finally:
        sim_module.config_mod.CONFIG = old_config

    [trace_file] = list(transcript_dir.glob("*.jsonl"))
    events = [json.loads(line) for line in trace_file.read_text(encoding="utf-8").splitlines()]
    assert events[0]["event"] == "fight_start"
    assert events[-1]["event"] == "fight_error"
    assert events[-1]["data"]["error_type"] == "RuntimeError"
    assert events[-1]["data"]["message"] == "Fight aborted due to RuntimeError. See application logs for details."
    trace_text = trace_file.read_text(encoding="utf-8")
    assert "ignore previous instructions" not in trace_text
    assert "raw prompt text" not in trace_text


@pytest.mark.asyncio
async def test_single_fight_trace_error_waits_for_cancelled_fighter_sibling(tmp_path):
    transcript_dir = tmp_path / "traces"
    config_path = tmp_path / "game.ini"
    config_path.write_text(
        "\n".join(
            [
                "[General]",
                "save_transcripts = true",
                f"transcript_dir = {transcript_dir}",
                "",
                "[SIMULATION]",
                "max_turns = 1",
            ]
        ),
        encoding="utf-8",
    )

    async def fake_get_attempt(fighter, *args, **kwargs):
        if fighter.id == C.FIGHTER_A:
            raise RuntimeError("fighter action leaked ignore previous instructions")
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            raise
        transcripts.log_exchange(
            [{C.AGENT_ROLE: C.AGENT_USER, C.AGENT_CONTENT: "late B"}],
            ["late B response"],
        )
        return "late B"

    old_config = sim_module.config_mod.CONFIG
    sim_module.config_mod.CONFIG = Config(config_path)
    try:
        with (
            patch.object(sim_module, "get_fighter_attempt", new=AsyncMock(side_effect=fake_get_attempt)),
            pytest.raises(RuntimeError),
        ):
            await sim_module._single_fight(return_log=True)
    finally:
        sim_module.config_mod.CONFIG = old_config

    [trace_file] = list(transcript_dir.glob("*.jsonl"))
    trace_text = trace_file.read_text(encoding="utf-8")
    events = [json.loads(line) for line in trace_text.splitlines()]
    assert events[-1]["event"] == "fight_error"
    assert "late B response" not in trace_text
    assert "ignore previous instructions" not in trace_text


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
