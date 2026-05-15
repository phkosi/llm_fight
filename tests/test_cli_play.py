import random
from unittest.mock import ANY, AsyncMock, MagicMock, patch

from click import unstyle
from typer.testing import CliRunner

from llm_fight.cli import app
from llm_fight.engine import constants as C
from llm_fight.engine.combat_log import CombatLog, CombatTurn
from llm_fight.judge import JudgePhase2FailureError
from llm_fight.simulation import FightEvent
from llm_fight.utils.token_counter import PromptBudgetError


def _plain_cli_output(result):
    return " ".join(unstyle(result.output).split())


def test_cli_play():
    runner = CliRunner()
    log = MagicMock(turns=[MagicMock()])
    with (
        patch(
            "llm_fight.simulation._single_fight",
            new=AsyncMock(return_value=({C.WINNER: "A", C.LOG_TURN: "1"}, log)),
        ) as mock_fight,
        patch("llm_fight.cli.render") as mock_render,
        patch("llm_fight.cli.ping_ollama", new=AsyncMock()),
    ):
        mock_render.RICH_AVAILABLE = True
        result = runner.invoke(app, ["play"])
    assert result.exit_code == 0
    assert "Winner: A" in result.output
    mock_fight.assert_called_once_with(
        fighter_a_section=None,
        fighter_b_section=None,
        return_log=True,
        on_event=ANY,
    )
    mock_render.make_turn_table.assert_called_once_with(log.turns[0], simple=False)


def test_cli_play_verbose():
    runner = CliRunner()
    log = MagicMock(turns=[MagicMock(), MagicMock()])
    with (
        patch(
            "llm_fight.simulation._single_fight",
            new=AsyncMock(return_value=({C.WINNER: "A", C.LOG_TURN: "1"}, log)),
        ) as mock_fight,
        patch("llm_fight.cli.render") as mock_render,
        patch("llm_fight.cli.ping_ollama", new=AsyncMock()),
    ):
        mock_render.RICH_AVAILABLE = True
        result = runner.invoke(app, ["play", "--verbose"])
    assert result.exit_code == 0
    mock_fight.assert_called_once_with(
        fighter_a_section=None,
        fighter_b_section=None,
        return_log=True,
        on_event=ANY,
    )
    assert mock_render.make_turn_table.call_count == 2
    for call in mock_render.make_turn_table.call_args_list:
        assert call.kwargs.get("simple") is False


def test_cli_play_verbose_routes_engine_logs_to_stderr():
    runner = CliRunner()
    log = MagicMock(turns=[])

    async def fake_fight(fighter_a_section=None, fighter_b_section=None, return_log=False, on_event=None):
        from llm_fight.engine.logger import logger

        logger.warning("engine warning on stderr")
        return {C.WINNER: C.DRAW, C.LOG_TURN: "1"}, log

    with (
        patch("llm_fight.simulation._single_fight", new=AsyncMock(side_effect=fake_fight)),
        patch("llm_fight.cli.ping_ollama", new=AsyncMock()),
    ):
        result = runner.invoke(app, ["play", "--verbose", "--simple-output"])

    assert result.exit_code == 0
    assert "engine warning on stderr" in result.stderr
    assert "engine warning on stderr" not in result.stdout


def test_cli_play_simple_output():
    runner = CliRunner()
    log = MagicMock(turns=[MagicMock()])
    with (
        patch(
            "llm_fight.simulation._single_fight",
            new=AsyncMock(return_value=({C.WINNER: "A", C.LOG_TURN: "1"}, log)),
        ) as mock_fight,
        patch("llm_fight.cli.render") as mock_render,
        patch("llm_fight.cli.ping_ollama", new=AsyncMock()),
    ):
        mock_render.RICH_AVAILABLE = True
        result = runner.invoke(app, ["play", "--simple-output"])
    assert result.exit_code == 0
    mock_fight.assert_called_once_with(
        fighter_a_section=None,
        fighter_b_section=None,
        return_log=True,
        on_event=ANY,
    )
    mock_render.make_turn_table.assert_called_once_with(log.turns[0], simple=True)


def test_cli_play_formats_configured_winner_display_name():
    runner = CliRunner()
    log = MagicMock(turns=[])
    result_payload = {
        C.WINNER: C.FIGHTER_A,
        C.LOG_TURN: "1",
        C.LOG_WINNER_DISPLAY_NAME: "Sir Galant",
    }
    with (
        patch("llm_fight.simulation._single_fight", new=AsyncMock(return_value=(result_payload, log))),
        patch("llm_fight.cli.render") as mock_render,
        patch("llm_fight.cli.ping_ollama", new=AsyncMock()),
    ):
        mock_render.RICH_AVAILABLE = True
        result = runner.invoke(app, ["play"])

    assert result.exit_code == 0
    assert "Winner: A (Sir Galant)" in result.output


def test_cli_play_simple_output_no_rich():
    runner = CliRunner()
    log = MagicMock(turns=[MagicMock()])
    with (
        patch(
            "llm_fight.simulation._single_fight",
            new=AsyncMock(return_value=({C.WINNER: "A", C.LOG_TURN: "1"}, log)),
        ) as mock_fight,
        patch("llm_fight.cli.render") as mock_render,
        patch("llm_fight.cli.ping_ollama", new=AsyncMock()),
    ):
        mock_render.RICH_AVAILABLE = False
        result = runner.invoke(app, ["play", "--simple-output"])
    assert result.exit_code == 0
    mock_fight.assert_called_once_with(
        fighter_a_section=None,
        fighter_b_section=None,
        return_log=True,
        on_event=ANY,
    )
    mock_render.make_turn_table.assert_called_once_with(log.turns[0], simple=True)


def test_cli_play_simple_output_separates_turn_phases():
    runner = CliRunner()
    log = CombatLog()
    log.append(
        CombatTurn(
            turn=1,
            attempt_A="A raises a shield",
            attempt_B="B throws smoke",
            judge_p1={
                "judgement_text": "The shield is ready before the smoke spreads.",
                "attempt_A_valid": True,
                "attempt_A_prob": "0.8",
                "attempt_B_valid": True,
                "attempt_B_prob": "0.4",
            },
            judge_p2={C.NARRATION: "A keeps their footing while B gains partial cover."},
        )
    )
    with (
        patch(
            "llm_fight.simulation._single_fight",
            new=AsyncMock(return_value=({C.WINNER: C.DRAW, C.LOG_TURN: "1"}, log)),
        ),
        patch("llm_fight.cli.ping_ollama", new=AsyncMock()),
    ):
        result = runner.invoke(app, ["play", "--simple-output"])

    assert result.exit_code == 0
    assert "Fighter A attempt: A raises a shield" in result.output
    assert "Fighter B attempt: B throws smoke" in result.output
    assert "Judge ruling:" in result.output
    assert "The shield is ready before the smoke spreads." in result.output
    assert "Outcome: A keeps their footing while B gains partial cover." in result.output
    assert result.output.index("Fighter B attempt") < result.output.index("Judge ruling:")
    assert result.output.index("Judge ruling:") < result.output.index("Outcome:")


def test_cli_play_simple_output_streams_progress_design_turns_and_tokens():
    runner = CliRunner()
    turn = CombatTurn(
        turn=1,
        attempt_A="A tests range",
        attempt_B="B guards",
        judge_p2={C.NARRATION: "The fighters measure each other."},
        state_A_before={C.STATUS: C.FighterStatus.FIGHTING, C.PAIN: 0, C.EXHAUSTION: 0, C.HEAT: 0, "parts": {}},
        state_A_after={C.STATUS: C.FighterStatus.FIGHTING, C.PAIN: 0, C.EXHAUSTION: 0, C.HEAT: 0, "parts": {}},
        state_B_before={C.STATUS: C.FighterStatus.FIGHTING, C.PAIN: 0, C.EXHAUSTION: 0, C.HEAT: 0, "parts": {}},
        state_B_after={C.STATUS: C.FighterStatus.FIGHTING, C.PAIN: 2, C.EXHAUSTION: 0, C.HEAT: 0, "parts": {}},
        rolls={
            C.FIGHTER_A: {
                "valid": True,
                "probability": 0.8,
                "probability_text": "0.8",
                "roll": 0.2,
                "success": True,
                "reason": "success",
            }
        },
    )
    log = CombatLog()
    log.append(turn)
    fighters = {
        C.FIGHTER_A: {
            C.DISPLAY_NAME: "Wings",
            "class_": "Winged Duelist",
            C.THEME: "sky mutant",
            C.LOADOUT: "hook blades",
            "environment": "an open arena",
            "parts": {"left_wing": {}, "second_head": {}},
            C.BUFFS: [],
            C.DEBUFFS: [],
        },
        C.FIGHTER_B: {
            "class_": "Knight",
            C.LOADOUT: "sword",
            "environment": "an open arena",
            "parts": {"head": {}, "torso": {}},
            C.BUFFS: [],
            C.DEBUFFS: [],
        },
    }

    async def fake_fight(fighter_a_section=None, fighter_b_section=None, return_log=False, on_event=None):
        on_event(FightEvent(C.FIGHT_EVENT_PROFILE_GENERATION_START, fighter_id=C.FIGHTER_A))
        on_event(FightEvent(C.FIGHT_EVENT_PROFILE_GENERATION_END, fighter_id=C.FIGHTER_A))
        on_event(FightEvent(C.FIGHT_EVENT_FIGHTERS_READY, data={"fighters": fighters}))
        on_event(
            FightEvent(
                C.FIGHT_EVENT_TOKEN_METADATA,
                data={"metadata": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14}},
            )
        )
        on_event(FightEvent(C.FIGHT_EVENT_TURN_COMPLETE, turn=1, data={"turn": turn}))
        on_event(FightEvent(C.FIGHT_EVENT_FIGHT_COMPLETE, turn=1, data={"result": {C.WINNER: C.DRAW}}))
        return {C.WINNER: C.DRAW, C.LOG_TURN: "1"}, log

    with (
        patch("llm_fight.simulation._single_fight", new=AsyncMock(side_effect=fake_fight)),
        patch("llm_fight.cli.ping_ollama", new=AsyncMock()),
    ):
        result = runner.invoke(app, ["play", "--simple-output"])

    assert result.exit_code == 0
    assert "Generating fighter profile (Fighter A)" in result.output
    assert "Fighter Designs" in result.output
    assert "Fighter A (Wings)" in result.output
    assert "Winged Duelist" in result.output
    assert "Turn 1:" in result.output
    assert "Rolls:" in result.output
    assert "Fighter A: success" in result.output
    assert "Mechanical changes:" in result.output
    assert "B pain +2 (0 -> 2)" in result.output
    assert "Token usage: prompt 10, completion 4, total 14" in result.output
    assert result.output.count("Turn 1:") == 1
    assert result.output.index("Generating fighter profile") < result.output.index("Fighter Designs")
    assert result.output.index("Fighter Designs") < result.output.index("Turn 1:")
    assert result.output.index("Turn 1:") < result.output.index("Token usage:")


def test_cli_play_suppresses_engine_logs_without_verbose_even_when_turn_logging_enabled(tmp_path):
    runner = CliRunner()
    cfg = tmp_path / "logs.ini"
    cfg.write_text("[General]\nollama_default_model = qwen3.6:35b\nlog_combat_turns = true\n")
    log = MagicMock(turns=[])

    from llm_fight import config as config_mod
    from llm_fight.engine import logger as logger_module

    original = config_mod.CONFIG
    previous_handlers = logger_module.logger.handlers[:]
    previous_level = logger_module.logger.level
    with (
        patch("llm_fight.engine.logger.update_logger_level") as mock_update,
        patch(
            "llm_fight.simulation._single_fight",
            new=AsyncMock(return_value=({C.WINNER: C.DRAW, C.LOG_TURN: "1"}, log)),
        ),
        patch("llm_fight.cli.render") as mock_render,
        patch("llm_fight.cli.ping_ollama", new=AsyncMock()),
    ):
        mock_render.RICH_AVAILABLE = True
        result = runner.invoke(app, ["play", "--config", str(cfg)])

    assert result.exit_code == 0
    mock_update.assert_called_once()
    assert logger_module.logger.handlers == previous_handlers
    assert logger_module.logger.level == previous_level
    config_mod.CONFIG = original


def test_cli_play_with_config(tmp_path):
    runner = CliRunner()
    cfg = tmp_path / "alt.ini"
    cfg.write_text("[General]\nollama_default_model = qwen3.6:35b\nmax_retries = 9\n")

    async def fake_fight(fighter_a_section=None, fighter_b_section=None, return_log=False, on_event=None):
        from llm_fight.config import CONFIG

        assert CONFIG.path == cfg
        assert CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_MAX_RETRIES, int) == 9
        assert CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, int) == 3
        return {C.WINNER: "B", C.LOG_TURN: "1"}, MagicMock(turns=[])

    from llm_fight import config as config_mod

    original = config_mod.CONFIG
    with (
        patch("llm_fight.engine.logger.update_logger_level") as mock_update,
        patch(
            "llm_fight.simulation._single_fight",
            new=AsyncMock(side_effect=fake_fight),
        ) as mock_fight,
        patch("llm_fight.cli.render") as mock_render,
        patch("llm_fight.cli.ping_ollama", new=AsyncMock()),
    ):
        mock_render.RICH_AVAILABLE = False
        result = runner.invoke(app, ["play", "--config", str(cfg), "--max-turns", "3", "--simple-output"])
    assert result.exit_code == 0
    assert "Winner: B" in result.output
    mock_fight.assert_called_once_with(fighter_a_section=None, fighter_b_section=None, return_log=True, on_event=ANY)
    mock_update.assert_called_once()
    config_mod.CONFIG = original


def test_cli_play_restores_config_after_runtime_failure(tmp_path):
    runner = CliRunner()
    cfg = tmp_path / "failure.ini"
    cfg.write_text("[General]\nollama_default_model = qwen3.6:35b\nmax_retries = 9\n", encoding="utf-8")

    from llm_fight import config as config_mod

    original = config_mod.CONFIG
    with patch("llm_fight.cli.ping_ollama", new=AsyncMock(side_effect=ConnectionError("offline"))):
        result = runner.invoke(app, ["play", "--config", str(cfg), "--simple-output"])

    assert result.exit_code != 0
    assert "offline" in result.output
    assert config_mod.CONFIG is original


def test_cli_play_explicit_config_requires_model_before_ping(tmp_path):
    runner = CliRunner()
    cfg = tmp_path / "no_model.ini"
    cfg.write_text("[General]\nmax_retries = 9\n", encoding="utf-8")
    ping = AsyncMock()

    with patch("llm_fight.cli.ping_ollama", new=ping):
        result = runner.invoke(app, ["play", "--config", str(cfg), "--simple-output"])

    assert result.exit_code != 0
    assert "ollama_default_model is required" in _plain_cli_output(result)
    ping.assert_not_awaited()


def test_cli_play_without_default_config_requires_model_before_ping(tmp_path):
    runner = CliRunner()
    ping = AsyncMock()

    with runner.isolated_filesystem(temp_dir=tmp_path), patch("llm_fight.cli.ping_ollama", new=ping):
        result = runner.invoke(app, ["play", "--simple-output"])

    assert result.exit_code != 0
    assert "ollama_default_model is required" in _plain_cli_output(result)
    ping.assert_not_awaited()


def test_cli_play_seeds_rng_from_active_config_after_rng_import(tmp_path):
    runner = CliRunner()
    cfg = tmp_path / "seeded.ini"
    cfg.write_text("[General]\nollama_default_model = qwen3.6:35b\n\n[SIMULATION]\nseed = 31415\n", encoding="utf-8")
    observed_rolls = []

    from llm_fight import config as config_mod
    from llm_fight import rng

    original_config = config_mod.CONFIG
    previous_rng_state = rng.get_state()
    rng.seed(5)
    expected_after_restore = random.Random(5)
    expected_active = random.Random(31415)

    async def fake_fight(fighter_a_section=None, fighter_b_section=None, return_log=False, on_event=None):
        observed_rolls.append(rng.rand())
        return {C.WINNER: C.DRAW, C.LOG_TURN: "1"}, MagicMock(turns=[])

    with (
        patch("llm_fight.simulation._single_fight", new=AsyncMock(side_effect=fake_fight)),
        patch("llm_fight.cli.ping_ollama", new=AsyncMock()),
    ):
        result = runner.invoke(app, ["play", "--config", str(cfg), "--simple-output"])

    assert result.exit_code == 0
    assert observed_rolls == [expected_active.random()]
    assert config_mod.CONFIG is original_config
    assert rng.rand() == expected_after_restore.random()
    rng.set_state(previous_rng_state)


def test_cli_fighter_options():
    runner = CliRunner()
    log = MagicMock(turns=[])
    with (
        patch(
            "llm_fight.simulation._single_fight",
            new=AsyncMock(return_value=({C.WINNER: "A", C.LOG_TURN: "1"}, log)),
        ) as mock_fight,
        patch("llm_fight.cli.render") as mock_render,
        patch("llm_fight.cli.ping_ollama", new=AsyncMock()),
    ):
        mock_render.RICH_AVAILABLE = False
        result = runner.invoke(app, ["play", "--fighter-a", "X", "--fighter-b", "Y", "--simple-output"])
    assert result.exit_code == 0
    mock_fight.assert_called_once_with(fighter_a_section="X", fighter_b_section="Y", return_log=True, on_event=ANY)


def test_cli_play_phase2_fail_closed_error_is_actionable():
    runner = CliRunner()
    with (
        patch(
            "llm_fight.simulation._single_fight",
            new=AsyncMock(
                side_effect=JudgePhase2FailureError("Judge Phase 2 failed after retries under fail_closed policy")
            ),
        ),
        patch("llm_fight.cli.ping_ollama", new=AsyncMock()),
    ):
        result = runner.invoke(app, ["play"])

    assert result.exit_code != 0
    assert "Judge Phase 2 failed after retries under fail_closed policy" in _plain_cli_output(result)


def test_cli_llm_validation_failure_is_actionable():
    runner = CliRunner()
    with (
        patch("llm_fight.cli.ping_ollama", new=AsyncMock()),
        patch(
            "llm_fight.simulation._single_fight",
            new=AsyncMock(side_effect=RuntimeError("Validation/JSON parsing failed after 2 attempts")),
        ),
    ):
        result = runner.invoke(app, ["play", "--simple-output"])

    assert result.exit_code != 0
    plain_output = _plain_cli_output(result)
    assert "LLM output could not be parsed" in plain_output
    assert "max_tokens_judge" in plain_output


def test_cli_prompt_budget_error_is_actionable():
    runner = CliRunner()
    error = PromptBudgetError(
        phase=C.PROMPT_PHASE_JUDGE_P2,
        prompt_tokens=900,
        context_limit=800,
        requested_max_tokens=512,
        reserved_completion=512,
        log_window_setting=C.CONFIG_JUDGE_LOG_WINDOW,
    )

    with (
        patch("llm_fight.cli.ping_ollama", new=AsyncMock()),
        patch("llm_fight.simulation._single_fight", new=AsyncMock(side_effect=error)),
    ):
        result = runner.invoke(app, ["play", "--simple-output"])

    assert result.exit_code != 0
    plain_output = _plain_cli_output(result)
    assert "Prompt budget exceeded for judge phase 2" in plain_output
    assert "prompt uses about 900 tokens" in plain_output
    assert "context limit is 800" in plain_output
    assert C.CONFIG_JUDGE_LOG_WINDOW in plain_output
