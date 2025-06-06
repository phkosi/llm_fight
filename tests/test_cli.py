from typer.testing import CliRunner

from src.cli import app
from unittest.mock import AsyncMock, patch
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
    fake_result = {C.WINNER: "A", C.LOG_TURN: "1"}
    with patch("src.simulation._single_fight", new=AsyncMock(return_value=fake_result)) as mock_fight:
        result = runner.invoke(app, ["play"])
    assert result.exit_code == 0
    assert "Winner: A" in result.output
    mock_fight.assert_called_once_with(fighter_a_section=None, fighter_b_section=None)


def test_cli_simulate(tmp_path):
    runner = CliRunner()
    dummy = tmp_path / "dummy.csv"
    with patch("src.simulation.run_batch", new=AsyncMock(return_value=dummy)) as mock_run_batch:
        result = runner.invoke(app, ["simulate", "--output-csv", "out.csv"])
    assert result.exit_code == 0
    mock_run_batch.assert_called_once_with(Path("out.csv"), fighter_a_section=None, fighter_b_section=None)
    assert "Simulation saved to" in result.output


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
    with patch(
        "src.simulation.run_batch",
        new=AsyncMock(side_effect=ClickException("invalid path")),
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
    with patch("src.simulation.run_batch", new=AsyncMock(side_effect=fake_run_batch)) as mock_run_batch:
        result = runner.invoke(app, ["simulate", "--config", str(cfg)])
    assert result.exit_code == 0
    mock_run_batch.assert_called_once_with(Path("sim_results.csv"), fighter_a_section=None, fighter_b_section=None)
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
    with patch("src.simulation._single_fight", new=AsyncMock(side_effect=fake_fight)) as mock_fight:
        result = runner.invoke(app, ["play", "--config", str(cfg)])
    assert result.exit_code == 0
    mock_fight.assert_called_once_with(fighter_a_section=None, fighter_b_section=None)
    config_mod.CONFIG = original


def test_cli_unexpected_argument():
    runner = CliRunner()
    result = runner.invoke(app, ["play", "extra"])
    assert result.exit_code != 0
    assert "unexpected extra argument" in result.output


def test_cli_fighter_options():
    runner = CliRunner()
    with patch(
        "src.simulation._single_fight",
        new=AsyncMock(return_value={C.WINNER: "A", C.LOG_TURN: "1"}),
    ) as mock_fight:
        result = runner.invoke(app, ["play", "--fighter-a", "X", "--fighter-b", "Y"])
    assert result.exit_code == 0
    mock_fight.assert_called_once_with(fighter_a_section="X", fighter_b_section="Y")


def test_cli_simulate_fighter_options(tmp_path):
    runner = CliRunner()
    dummy = tmp_path / "dummy.csv"
    with patch(
        "src.simulation.run_batch",
        new=AsyncMock(return_value=dummy),
    ) as mock_run_batch:
        result = runner.invoke(app, ["simulate", "--fighter-a", "X", "--fighter-b", "Y"])
    assert result.exit_code == 0
    mock_run_batch.assert_called_once_with(Path("sim_results.csv"), fighter_a_section="X", fighter_b_section="Y")
