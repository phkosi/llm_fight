import csv
from typer.testing import CliRunner

from llm_fight.cli import app
from unittest.mock import ANY, AsyncMock, MagicMock, patch
from pathlib import Path
from click import ClickException
from logging import CRITICAL
from llm_fight.engine import constants as C
from llm_fight.engine.combat_log import CombatLog, CombatTurn
from llm_fight.simulation import FightEvent
from llm_fight.utils.token_counter import PromptBudgetError


def _write_batch_csv(path, rows):
    with path.open("w", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=[C.WINNER, C.LOG_TURN])
        writer.writeheader()
        writer.writerows(rows)


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Usage" in result.output


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
    )
    log = CombatLog()
    log.append(turn)
    fighters = {
        C.FIGHTER_A: {
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
    assert "Winged Duelist" in result.output
    assert "Turn 1:" in result.output
    assert "Token usage: prompt 10, completion 4, total 14" in result.output
    assert result.output.count("Turn 1:") == 1
    assert result.output.index("Generating fighter profile") < result.output.index("Fighter Designs")
    assert result.output.index("Fighter Designs") < result.output.index("Turn 1:")
    assert result.output.index("Turn 1:") < result.output.index("Token usage:")


def test_cli_play_suppresses_engine_logs_without_verbose_even_when_turn_logging_enabled(tmp_path):
    runner = CliRunner()
    cfg = tmp_path / "logs.ini"
    cfg.write_text("[General]\nlog_combat_turns = true\n")
    log = MagicMock(turns=[])

    from llm_fight import config as config_mod

    original = config_mod.CONFIG
    with (
        patch("llm_fight.engine.logger.update_logger_level") as mock_update,
        patch("llm_fight.engine.logger.logger") as mock_logger,
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
    mock_logger.setLevel.assert_called_once_with(CRITICAL)
    config_mod.CONFIG = original


def test_cli_simulate(tmp_path):
    runner = CliRunner()
    dummy = tmp_path / "dummy.csv"
    _write_batch_csv(dummy, [{C.WINNER: "A", C.LOG_TURN: "1"}])
    with (
        patch("llm_fight.simulation.run_batch", new=AsyncMock(return_value=dummy)) as mock_run_batch,
        patch("llm_fight.cli.ping_ollama", new=AsyncMock()),
    ):
        result = runner.invoke(app, ["simulate", "--output-csv", "out.csv"])
    assert result.exit_code == 0
    mock_run_batch.assert_called_once_with(Path("out.csv"), fighter_a_section=None, fighter_b_section=None)
    assert "Simulation saved to" in result.output


def test_cli_simulate_verbose(tmp_path):
    runner = CliRunner()
    dummy = tmp_path / "dummy.csv"
    dummy.write_text("winner,turn\nA,1\n")
    with (
        patch(
            "llm_fight.simulation.run_batch",
            new=AsyncMock(return_value=dummy),
        ) as mock_run_batch,
        patch("llm_fight.cli.render") as mock_render,
        patch("llm_fight.cli.ping_ollama", new=AsyncMock()),
    ):
        mock_render.RICH_AVAILABLE = True
        mock_render.make_summary_table.return_value = "table"
        result = runner.invoke(app, ["simulate", "--verbose"])
    assert result.exit_code == 0
    assert mock_run_batch.call_args.kwargs["progress"] is not None
    mock_render.make_summary_table.assert_called_once()


def test_cli_unknown_option():
    runner = CliRunner()
    result = runner.invoke(app, ["simulate", "--unknown"])
    assert result.exit_code != 0
    assert "No such option" in result.output


def test_cli_missing_option_value():
    runner = CliRunner()
    result = runner.invoke(app, ["simulate", "--output-csv"])
    assert result.exit_code != 0
    assert "requires an argument" in result.output


def test_cli_invalid_path():
    runner = CliRunner()
    with (
        patch(
            "llm_fight.simulation.run_batch",
            new=AsyncMock(side_effect=ClickException("invalid path")),
        ),
        patch("llm_fight.cli.ping_ollama", new=AsyncMock()),
    ):
        result = runner.invoke(app, ["simulate", "--output-csv", "bad/out.csv"])
    assert result.exit_code != 0
    assert "invalid path" in result.output


def test_cli_invalid_config_file(tmp_path):
    runner = CliRunner()
    cfg = tmp_path / "bad.ini"
    cfg.write_text("not an ini file")

    result = runner.invoke(app, ["play", "--config", str(cfg), "--simple-output"])

    assert result.exit_code != 0
    assert "Could not read config file" in result.output


def test_cli_simulate_with_config(tmp_path):
    runner = CliRunner()
    cfg = tmp_path / "alt.ini"
    cfg.write_text("[SIMULATION]\nseed = 77\n")

    async def fake_run_batch(output_csv, fighter_a_section=None, fighter_b_section=None):
        from llm_fight.config import CONFIG

        assert CONFIG.path == cfg
        assert CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_SEED, int) == 77
        dummy = tmp_path / "dummy.csv"
        _write_batch_csv(dummy, [{C.WINNER: "A", C.LOG_TURN: "1"}])
        return dummy

    from llm_fight import config as config_mod

    original = config_mod.CONFIG
    with (
        patch("llm_fight.engine.logger.update_logger_level") as mock_update,
        patch(
            "llm_fight.simulation.run_batch",
            new=AsyncMock(side_effect=fake_run_batch),
        ) as mock_run_batch,
        patch("llm_fight.cli.ping_ollama", new=AsyncMock()),
    ):
        result = runner.invoke(app, ["simulate", "--config", str(cfg)])
    assert result.exit_code == 0
    mock_run_batch.assert_called_once_with(Path("sim_results.csv"), fighter_a_section=None, fighter_b_section=None)
    mock_update.assert_called_once()
    config_mod.CONFIG = original


def test_cli_play_with_config(tmp_path):
    runner = CliRunner()
    cfg = tmp_path / "alt.ini"
    cfg.write_text("[General]\nmax_retries = 9\n")

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


def test_cli_unexpected_argument():
    runner = CliRunner()
    result = runner.invoke(app, ["play", "extra"])
    assert result.exit_code != 0
    assert "unexpected extra argument" in result.output


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


def test_cli_simulate_fighter_options(tmp_path):
    runner = CliRunner()
    dummy = tmp_path / "dummy.csv"
    _write_batch_csv(dummy, [{C.WINNER: "A", C.LOG_TURN: "1"}])
    with (
        patch(
            "llm_fight.simulation.run_batch",
            new=AsyncMock(return_value=dummy),
        ) as mock_run_batch,
        patch("llm_fight.cli.ping_ollama", new=AsyncMock()),
    ):
        result = runner.invoke(app, ["simulate", "--fighter-a", "X", "--fighter-b", "Y"])
    assert result.exit_code == 0
    mock_run_batch.assert_called_once_with(Path("sim_results.csv"), fighter_a_section="X", fighter_b_section="Y")


def test_cli_simulate_smoke_overrides(tmp_path):
    runner = CliRunner()
    dummy = tmp_path / "dummy.csv"
    _write_batch_csv(dummy, [{C.WINNER: "A", C.LOG_TURN: "1"}])

    async def fake_run_batch(output_csv, fighter_a_section=None, fighter_b_section=None):
        from llm_fight.config import CONFIG

        assert CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_RUNS, int) == 3
        assert CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_MAX_TURNS, int) == 4
        return dummy

    from llm_fight import config as config_mod

    original = config_mod.CONFIG
    with (
        patch("llm_fight.simulation.run_batch", new=AsyncMock(side_effect=fake_run_batch)),
        patch("llm_fight.cli.ping_ollama", new=AsyncMock()),
    ):
        result = runner.invoke(app, ["simulate", "--runs", "3", "--max-turns", "4"])

    assert result.exit_code == 0
    config_mod.CONFIG = original


def test_cli_simulate_exits_nonzero_for_all_error_rows(tmp_path):
    runner = CliRunner()
    dummy = tmp_path / "errors.csv"
    _write_batch_csv(
        dummy,
        [
            {C.WINNER: C.BATCH_ERROR_WINNER, C.LOG_TURN: "0"},
            {C.WINNER: C.BATCH_ERROR_WINNER, C.LOG_TURN: "0"},
        ],
    )

    with (
        patch("llm_fight.simulation.run_batch", new=AsyncMock(return_value=dummy)),
        patch("llm_fight.cli.ping_ollama", new=AsyncMock()),
    ):
        result = runner.invoke(app, ["simulate", "--runs", "2"])

    assert result.exit_code == 1
    assert "Simulation saved to" in result.output
    assert "2 error row(s)" in result.output


def test_cli_simulate_exits_nonzero_for_mixed_error_rows(tmp_path):
    runner = CliRunner()
    dummy = tmp_path / "mixed.csv"
    _write_batch_csv(
        dummy,
        [
            {C.WINNER: "A", C.LOG_TURN: "1"},
            {C.WINNER: C.BATCH_ERROR_WINNER, C.LOG_TURN: "0"},
        ],
    )

    with (
        patch("llm_fight.simulation.run_batch", new=AsyncMock(return_value=dummy)),
        patch("llm_fight.cli.ping_ollama", new=AsyncMock()),
    ):
        result = runner.invoke(app, ["simulate", "--runs", "2"])

    assert result.exit_code == 1
    assert "1 error row(s)" in result.output
    assert "1 completed successfully" in result.output


def test_cli_simulate_continue_on_error_exits_zero_with_warning(tmp_path):
    runner = CliRunner()
    dummy = tmp_path / "mixed.csv"
    _write_batch_csv(
        dummy,
        [
            {C.WINNER: "A", C.LOG_TURN: "1"},
            {C.WINNER: C.BATCH_ERROR_WINNER, C.LOG_TURN: "0"},
        ],
    )

    with (
        patch("llm_fight.simulation.run_batch", new=AsyncMock(return_value=dummy)),
        patch("llm_fight.cli.ping_ollama", new=AsyncMock()),
    ):
        result = runner.invoke(app, ["simulate", "--runs", "2", "--continue-on-error"])

    assert result.exit_code == 0
    assert "1 error row(s)" in result.output


def test_cli_simulate_prompt_budget_error_is_actionable():
    runner = CliRunner()
    error = PromptBudgetError(
        phase=C.PROMPT_PHASE_FIGHTER_ACTION,
        prompt_tokens=700,
        context_limit=600,
        requested_max_tokens=64,
        reserved_completion=64,
        log_window_setting=C.CONFIG_FIGHTER_LOG_WINDOW,
    )

    with (
        patch("llm_fight.simulation.run_batch", new=AsyncMock(side_effect=error)),
        patch("llm_fight.cli.ping_ollama", new=AsyncMock()),
    ):
        result = runner.invoke(app, ["simulate"])

    assert result.exit_code != 0
    assert "Prompt budget exceeded for fighter action" in result.output
    assert C.CONFIG_FIGHTER_LOG_WINDOW in result.output


def test_cli_simulate_invalid_config_fails_before_ping(tmp_path):
    runner = CliRunner()
    cfg = tmp_path / "bad_batch.ini"
    cfg.write_text("[SIMULATION]\nconcurrent_runs = 0\n")

    from llm_fight import config as config_mod

    original = config_mod.CONFIG
    ping = AsyncMock()
    run_batch = AsyncMock()
    try:
        with (
            patch("llm_fight.cli.ping_ollama", new=ping),
            patch("llm_fight.simulation.run_batch", new=run_batch),
        ):
            result = runner.invoke(app, ["simulate", "--config", str(cfg)])
    finally:
        config_mod.CONFIG = original

    assert result.exit_code != 0
    assert "concurrent_runs" in result.output
    ping.assert_not_awaited()
    run_batch.assert_not_awaited()


def test_cli_simulate_negative_runs_override_fails_before_ping():
    runner = CliRunner()
    ping = AsyncMock()

    with patch("llm_fight.cli.ping_ollama", new=ping):
        result = runner.invoke(app, ["simulate", "--runs", "-1"])

    assert result.exit_code != 0
    assert "--runs must be 0 or greater" in result.output
    ping.assert_not_awaited()


def test_cli_ollama_unreachable():
    runner = CliRunner()
    with patch("llm_fight.cli.ping_ollama", new=AsyncMock(side_effect=ConnectionError("offline"))):
        result = runner.invoke(app, ["play"])
    assert result.exit_code != 0
    assert "offline" in result.output


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
    assert "LLM output could not be parsed" in result.output
    assert "max_tokens_judge" in result.output


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
    assert "Prompt budget exceeded for judge phase 2" in result.output
    assert "prompt uses about 900 tokens" in result.output
    assert "context limit is 800" in result.output
    assert C.CONFIG_JUDGE_LOG_WINDOW in result.output
