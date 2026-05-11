from typer.testing import CliRunner

from llm_fight.cli import app
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
from click import ClickException
from llm_fight.engine import constants as C


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
    )
    mock_render.make_turn_table.assert_called_once_with(log.turns[0], simple=True)


def test_cli_simulate(tmp_path):
    runner = CliRunner()
    dummy = tmp_path / "dummy.csv"
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
        return Path("dummy.csv")

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

    async def fake_fight(fighter_a_section=None, fighter_b_section=None, return_log=False):
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
    mock_fight.assert_called_once_with(fighter_a_section=None, fighter_b_section=None, return_log=True)
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
    mock_fight.assert_called_once_with(fighter_a_section="X", fighter_b_section="Y", return_log=True)


def test_cli_simulate_fighter_options(tmp_path):
    runner = CliRunner()
    dummy = tmp_path / "dummy.csv"
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
