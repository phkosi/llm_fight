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
    with patch("src.simulation._single_fight", new=AsyncMock(return_value=fake_result)):
        result = runner.invoke(app, ["play"])
    assert result.exit_code == 0
    assert "Winner: A" in result.output


def test_cli_simulate(tmp_path):
    runner = CliRunner()
    dummy = tmp_path / "dummy.csv"
    with patch("src.simulation.run_batch", new=AsyncMock(return_value=dummy)) as mock_run_batch:
        result = runner.invoke(app, ["simulate", "--output-csv", "out.csv"])
    assert result.exit_code == 0
    mock_run_batch.assert_called_once_with(Path("out.csv"))
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


def test_cli_unexpected_argument():
    runner = CliRunner()
    result = runner.invoke(app, ["play", "extra"])
    assert result.exit_code != 0
    assert "unexpected extra argument" in result.output
