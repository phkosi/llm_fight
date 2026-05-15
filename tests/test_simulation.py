import json
import random
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import llm_fight.simulation as sim_module
from llm_fight.agents import ChatResult
from llm_fight.config import CONFIG, Config

# from llm_fight.anatomy import PRESETS as ANATOMY_PRESETS # No longer needed for this test's mocking strategy
from llm_fight.engine import constants as C
from llm_fight.profiles import build_fighter_profile
from llm_fight.state import FighterState  # Keep for spec


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


@patch("llm_fight.simulation.get_fighter_attempt", new_callable=AsyncMock)
@patch("llm_fight.simulation.judge_phase1", new_callable=AsyncMock)
@patch("llm_fight.simulation.judge_phase2", new_callable=AsyncMock)
@patch("llm_fight.state.FighterState.from_preset")  # This is the crucial mock for instances inside _single_fight
@pytest.mark.asyncio
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

    async def p2_side_effect(p2_input_state, rolls, **kwargs):
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
    fight_rng.random.return_value = 0.0

    with (
        patch.object(sim_module, "get_fighter_attempt", new=AsyncMock(side_effect=fake_get_attempt)),
        patch.object(sim_module, "judge_phase1", new=AsyncMock(side_effect=fake_judge_p1)),
        patch.object(sim_module, "judge_phase2", new=AsyncMock(side_effect=fake_judge_p2)),
        patch.object(sim_module, "rand", side_effect=AssertionError("global rand should not be used")) as mock_rand,
    ):
        result, combat_log = await sim_module._single_fight(fight_rng=fight_rng, return_log=True)

    assert result[C.WINNER] == C.FIGHTER_A
    assert fight_rng.random.call_count == 1
    mock_rand.assert_not_called()
    turn_rolls = combat_log.turns[0].rolls
    assert turn_rolls[C.FIGHTER_A]["roll"] == 0.0
    assert turn_rolls[C.FIGHTER_A]["success"] is True
    assert turn_rolls[C.FIGHTER_A]["reason"] == "success"
    assert turn_rolls[C.FIGHTER_B]["roll"] is None
    assert turn_rolls[C.FIGHTER_B]["success"] is False
    assert turn_rolls[C.FIGHTER_B]["reason"] == "zero_probability"


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
    assert "llm_output_retry" in trace_text
    assert "invalid_generated_profile" in trace_text
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
