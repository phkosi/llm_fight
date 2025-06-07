from typer.testing import CliRunner

from src.cli import app
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
from click import ClickException
from src.engine import constants as C


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Usage" in result.output


def test_cli_play():
    runner = CliRunner()
    turn = MagicMock()

    async def fake_fight(*args, **kwargs):
        kwargs["on_turn"](turn)
        return {C.WINNER: "A", C.LOG_TURN: "1"}

    with (
        patch("src.simulation._single_fight", new=AsyncMock(side_effect=fake_fight)) as mock_fight,
        patch("src.cli.render") as mock_render,
        patch("src.cli.ping_ollama", new=AsyncMock()),
    ):
        mock_render.RICH_AVAILABLE = True
        result = runner.invoke(app, ["play"])
    assert result.exit_code == 0
    assert "Winner: A" in result.output
    mock_fight.assert_called_once()
    assert mock_fight.call_args.kwargs["fighter_a_section"] is None
    assert mock_fight.call_args.kwargs["fighter_b_section"] is None
    assert callable(mock_fight.call_args.kwargs["on_turn"])
    mock_render.make_turn_table.assert_called_once_with(turn, simple=False)


def test_cli_play_verbose():
    runner = CliRunner()
    turns = [MagicMock(), MagicMock()]

    async def fake_fight(*args, **kwargs):
        for t in turns:
            kwargs["on_turn"](t)
        return {C.WINNER: "A", C.LOG_TURN: "1"}

    with (
        patch("src.simulation._single_fight", new=AsyncMock(side_effect=fake_fight)) as mock_fight,
        patch("src.cli.render") as mock_render,
        patch("src.cli.ping_ollama", new=AsyncMock()),
    ):
        mock_render.RICH_AVAILABLE = True
        result = runner.invoke(app, ["play", "--verbose"])
    assert result.exit_code == 0
    mock_fight.assert_called_once()
    assert mock_fight.call_args.kwargs["fighter_a_section"] is None
    assert mock_fight.call_args.kwargs["fighter_b_section"] is None
    assert callable(mock_fight.call_args.kwargs["on_turn"])
    assert mock_render.make_turn_table.call_count == 2
    for call, turn in zip(mock_render.make_turn_table.call_args_list, turns):
        assert call.args[0] is turn
        assert call.kwargs.get("simple") is False


def test_cli_play_simple_output():
    runner = CliRunner()
    turn = MagicMock()

    async def fake_fight(*args, **kwargs):
        kwargs["on_turn"](turn)
        return {C.WINNER: "A", C.LOG_TURN: "1"}

    with (
        patch("src.simulation._single_fight", new=AsyncMock(side_effect=fake_fight)) as mock_fight,
        patch("src.cli.render") as mock_render,
        patch("src.cli.ping_ollama", new=AsyncMock()),
    ):
        mock_render.RICH_AVAILABLE = True
        result = runner.invoke(app, ["play", "--simple-output"])
    assert result.exit_code == 0
    mock_fight.assert_called_once()
    assert mock_fight.call_args.kwargs["fighter_a_section"] is None
    assert mock_fight.call_args.kwargs["fighter_b_section"] is None
    assert callable(mock_fight.call_args.kwargs["on_turn"])
    mock_render.make_turn_table.assert_called_once_with(turn, simple=True)


def test_cli_play_simple_output_no_rich():
    runner = CliRunner()
    turn = MagicMock()

    async def fake_fight(*args, **kwargs):
        kwargs["on_turn"](turn)
        return {C.WINNER: "A", C.LOG_TURN: "1"}

    with (
        patch("src.simulation._single_fight", new=AsyncMock(side_effect=fake_fight)) as mock_fight,
        patch("src.cli.render") as mock_render,
        patch("src.cli.ping_ollama", new=AsyncMock()),
    ):
        mock_render.RICH_AVAILABLE = False
        result = runner.invoke(app, ["play", "--simple-output"])
    assert result.exit_code == 0
    mock_fight.assert_called_once()
    assert callable(mock_fight.call_args.kwargs["on_turn"])
    mock_render.make_turn_table.assert_called_once_with(turn, simple=True)


def test_cli_simulate(tmp_path):
    runner = CliRunner()
    dummy = tmp_path / "dummy.csv"
    with (
        patch("src.simulation.run_batch", new=AsyncMock(return_value=dummy)) as mock_run_batch,
        patch("src.cli.ping_ollama", new=AsyncMock()),
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
            "src.simulation.run_batch",
            new=AsyncMock(return_value=dummy),
        ) as mock_run_batch,
        patch("src.cli.render") as mock_render,
        patch("src.cli.ping_ollama", new=AsyncMock()),
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
            "src.simulation.run_batch",
            new=AsyncMock(side_effect=ClickException("invalid path")),
        ),
        patch("src.cli.ping_ollama", new=AsyncMock()),
    ):
        result = runner.invoke(app, ["simulate", "--output-csv", "bad/out.csv"])
    assert result.exit_code != 0
    assert "invalid path" in result.output


def test_cli_simulate_with_config(tmp_path):
    runner = CliRunner()
    cfg = tmp_path / "alt.ini"
    cfg.write_text("[SIMULATION]\nseed = 77\n")

    async def fake_run_batch(output_csv, fighter_a_section=None, fighter_b_section=None):
        from src.config import CONFIG

        assert CONFIG.path == cfg
        assert CONFIG.get(C.CONFIG_SIMULATION, C.CONFIG_SEED, int) == 77
        return Path("dummy.csv")

    from src import config as config_mod

    original = config_mod.CONFIG
    with (
        patch("src.engine.logger.update_logger_level") as mock_update,
        patch(
            "src.simulation.run_batch",
            new=AsyncMock(side_effect=fake_run_batch),
        ) as mock_run_batch,
        patch("src.cli.ping_ollama", new=AsyncMock()),
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

    async def fake_fight(fighter_a_section=None, fighter_b_section=None):
        from src.config import CONFIG

        assert CONFIG.path == cfg
        assert CONFIG.get(C.CONFIG_GENERAL, C.CONFIG_MAX_RETRIES, int) == 9
        return {C.WINNER: "B", C.LOG_TURN: "1"}

    from src import config as config_mod

    original = config_mod.CONFIG
    with (
        patch("src.engine.logger.update_logger_level") as mock_update,
        patch(
            "src.simulation._single_fight",
            new=AsyncMock(side_effect=fake_fight),
        ) as mock_fight,
        patch("src.cli.render") as mock_render,
        patch("src.cli.ping_ollama", new=AsyncMock()),
    ):
        mock_render.RICH_AVAILABLE = False
        result = runner.invoke(app, ["play", "--config", str(cfg)])
    assert result.exit_code != 0
    assert "rich" in result.output.lower()
    mock_fight.assert_not_called()
    mock_update.assert_not_called()
    config_mod.CONFIG = original


def test_cli_unexpected_argument():
    runner = CliRunner()
    result = runner.invoke(app, ["play", "extra"])
    assert result.exit_code != 0
    assert "unexpected extra argument" in result.output


def test_cli_fighter_options():
    runner = CliRunner()
    with (
        patch(
            "src.simulation._single_fight",
            new=AsyncMock(return_value={C.WINNER: "A", C.LOG_TURN: "1"}),
        ) as mock_fight,
        patch("src.cli.render") as mock_render,
        patch("src.cli.ping_ollama", new=AsyncMock()),
    ):
        mock_render.RICH_AVAILABLE = False
        result = runner.invoke(app, ["play", "--fighter-a", "X", "--fighter-b", "Y"])
    assert result.exit_code != 0
    assert "rich" in result.output.lower()
    mock_fight.assert_not_called()


def test_cli_simulate_fighter_options(tmp_path):
    runner = CliRunner()
    dummy = tmp_path / "dummy.csv"
    with (
        patch(
            "src.simulation.run_batch",
            new=AsyncMock(return_value=dummy),
        ) as mock_run_batch,
        patch("src.cli.ping_ollama", new=AsyncMock()),
    ):
        result = runner.invoke(app, ["simulate", "--fighter-a", "X", "--fighter-b", "Y"])
    assert result.exit_code == 0
    mock_run_batch.assert_called_once_with(Path("sim_results.csv"), fighter_a_section="X", fighter_b_section="Y")


def test_cli_ollama_unreachable():
    runner = CliRunner()
    with patch("src.cli.ping_ollama", new=AsyncMock(side_effect=ClickException("offline"))):
        result = runner.invoke(app, ["play"])
    assert result.exit_code != 0
    assert "offline" in result.output
